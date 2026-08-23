from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

import httpx

from app.config import CM_BONUS_ADMIN_CHAT_ID, CM_BONUS_BOT_TOKEN, CM_BONUS_PROXY_URL, TG_PROXY_URL
from app.core import get_db_connection
from app.services.clubs import ensure_club_bonus_chat_column

_cm_bonus_tables_ready = False


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def ensure_cm_bonus_tables(cursor) -> None:
    """Create Cyber Bonus bonus balance, ledger and redeem request tables lazily."""
    global _cm_bonus_tables_ready
    if _cm_bonus_tables_ready:
        return

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cm_bonus_balances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cm_bonus_balance (club_id, guest_id),
            KEY idx_cm_bonus_balance_guest (guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cm_bonus_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            balance_after INT NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_id VARCHAR(120) NULL,
            description VARCHAR(255) NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'done',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cm_bonus_source (club_id, guest_id, source_type, source_id),
            KEY idx_cm_bonus_guest_created (club_id, guest_id, created_at),
            KEY idx_cm_bonus_source_type (source_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cm_bonus_redeem_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            admin_chat_id VARCHAR(80) NULL,
            telegram_message_id BIGINT NULL,
            error_text TEXT NULL,
            requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME NULL,
            KEY idx_cm_bonus_redeem_guest (club_id, guest_id, requested_at),
            KEY idx_cm_bonus_redeem_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    _ensure_column(cursor, "cm_bonus_redeem_requests", "processed_by_telegram_id", "BIGINT NULL")
    _ensure_column(cursor, "cm_bonus_redeem_requests", "processed_by_username", "VARCHAR(255) NULL")
    _ensure_column(cursor, "cm_bonus_redeem_requests", "notify_attempts", "INT NOT NULL DEFAULT 0")
    _ensure_column(cursor, "cm_bonus_redeem_requests", "last_notify_attempt_at", "DATETIME NULL")
    _ensure_column(cursor, "cm_bonus_redeem_requests", "next_notify_attempt_at", "DATETIME NULL")
    _ensure_column(cursor, "cm_bonus_transactions", "expires_at", "DATETIME NULL")
    _ensure_column(cursor, "cm_bonus_transactions", "expires_status", "VARCHAR(30) NOT NULL DEFAULT 'none'")
    _ensure_column(cursor, "cm_bonus_transactions", "expired_at", "DATETIME NULL")
    _ensure_column(cursor, "cm_bonus_transactions", "expiration_transaction_id", "INT NULL")
    _cm_bonus_tables_ready = True


def _ensure_balance_row(cursor, guest_id: int, club_id: int) -> None:
    ensure_cm_bonus_tables(cursor)
    cursor.execute(
        """
        INSERT IGNORE INTO cm_bonus_balances (club_id, guest_id, balance)
        VALUES (%s, %s, 0)
        """,
        (club_id, guest_id),
    )


def _get_balance_for_update(cursor, guest_id: int, club_id: int) -> int:
    _ensure_balance_row(cursor, guest_id, club_id)
    cursor.execute(
        """
        SELECT balance
        FROM cm_bonus_balances
        WHERE club_id = %s AND guest_id = %s
        FOR UPDATE
        """,
        (club_id, guest_id),
    )
    row = cursor.fetchone() or {}
    return int(row.get("balance") or 0)


def _transaction_exists(cursor, guest_id: int, club_id: int, source_type: str, source_id: str | None) -> bool:
    if source_id is None:
        return False
    ensure_cm_bonus_tables(cursor)
    cursor.execute(
        """
        SELECT id
        FROM cm_bonus_transactions
        WHERE club_id = %s
          AND guest_id = %s
          AND source_type = %s
          AND source_id = %s
        LIMIT 1
        """,
        (club_id, guest_id, source_type, str(source_id)),
    )
    return bool(cursor.fetchone())


def add_cm_bonus_transaction(
    cursor,
    guest_id: int,
    club_id: int,
    amount: int,
    source_type: str,
    source_id: str | None = None,
    description: str | None = None,
    status: str = "done",
    expires_at: datetime | None = None,
    expires_status: str | None = None,
    created_at: datetime | None = None,
) -> bool:
    """Change КБ balance and write a ledger row. Returns False for duplicate idempotent sources."""
    amount = int(amount or 0)
    if amount == 0:
        return False

    source_id_str = str(source_id) if source_id is not None else None
    if _transaction_exists(cursor, guest_id, club_id, source_type, source_id_str):
        return False

    balance = _get_balance_for_update(cursor, guest_id, club_id)
    balance_after = balance + amount
    if balance_after < 0:
        raise ValueError("Недостаточно бонусов")

    cursor.execute(
        """
        UPDATE cm_bonus_balances
        SET balance = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE club_id = %s AND guest_id = %s
        """,
        (balance_after, club_id, guest_id),
    )
    cursor.execute(
        """
        INSERT INTO cm_bonus_transactions (
            club_id,
            guest_id,
            amount,
            balance_after,
            source_type,
            source_id,
            description,
            status,
            expires_at,
            expires_status,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            club_id,
            guest_id,
            amount,
            balance_after,
            source_type,
            source_id_str,
            description,
            status,
            expires_at,
            expires_status or ("active" if expires_at and amount > 0 else "none"),
            created_at or _utcnow(),
        ),
    )
    return True


def award_cm_bonuses_for_wheel_prize(
    cursor,
    guest_id: int,
    club_id: int,
    spin_id: int,
    prize: dict[str, Any] | None,
) -> bool:
    if not prize:
        return False
    bonus_amount = int(prize.get("bonus_amount") or 0)
    if bonus_amount <= 0:
        return False

    prize_name = prize.get("name") or "приз колеса"
    return add_cm_bonus_transaction(
        cursor=cursor,
        guest_id=guest_id,
        club_id=club_id,
        amount=bonus_amount,
        source_type="wheel_prize",
        source_id=str(spin_id),
        description=f"Приз колеса: {prize_name}",
        status="done",
    )


def get_cm_bonus_balance(guest_id: int, club_id: int) -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            _ensure_balance_row(cursor, guest_id, club_id)
            cursor.execute(
                """
                SELECT balance
                FROM cm_bonus_balances
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                (club_id, guest_id),
            )
            row = cursor.fetchone() or {}
        conn.commit()
        return max(int(row.get("balance") or 0), 0)
    finally:
        conn.close()


def get_cm_bonus_history(guest_id: int, club_id: int, limit: int = 20):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT id, amount, balance_after, source_type, source_id, description, status, created_at
                FROM cm_bonus_transactions
                WHERE club_id = %s AND guest_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, limit),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def _format_phone(phone: str | None) -> str:
    if not phone:
        return "не указан"
    value = str(phone).strip()
    if len(value) == 10 and value.isdigit():
        return "+7" + value
    return value


def get_cm_bonus_admin_chat_id_for_club(club_id: int) -> str | None:
    """Return per-club Telegram chat id for КБ redeem requests.

    CM_BONUS_ADMIN_CHAT_ID from .env is kept as optional fallback for old setups,
    but the main source is clubs.cm_bonus_admin_chat_id.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_club_bonus_chat_column(cursor)
            cursor.execute(
                """
                SELECT cm_bonus_admin_chat_id
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            row = cursor.fetchone() or {}
        conn.commit()
    finally:
        conn.close()

    chat_id = str(row.get("cm_bonus_admin_chat_id") or "").strip()
    if chat_id:
        return chat_id

    # Fallback for dev/old installations. For production fill the field in club settings.
    fallback = str(CM_BONUS_ADMIN_CHAT_ID or "").strip()
    return fallback or None


def _html(value: Any) -> str:
    return escape(str(value or ""), quote=False)


def _format_dt(value: Any) -> str:
    if not value:
        return "не указано"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except AttributeError:
        return str(value)


def get_cm_bonus_redeem_request_by_id(request_id: int) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT r.*,
                       g.fio AS guest_name,
                       g.phone AS guest_phone
                FROM cm_bonus_redeem_requests r
                LEFT JOIN guests g
                  ON g.guest_id = r.guest_id
                 AND g.club_id = r.club_id
                WHERE r.id = %s
                LIMIT 1
                """,
                (request_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def format_cm_bonus_redeem_message(request: dict[str, Any], credited: bool = False) -> str:
    request_id = request.get("id")
    guest_name = _html(request.get("guest_name") or "Гость")
    phone = _html(_format_phone(request.get("guest_phone")))
    guest_id = _html(request.get("guest_id"))
    club_id = _html(request.get("club_id"))
    amount = _html(request.get("amount"))

    status = request.get("status") or "pending"
    if credited or status == "credited":
        processed_by = request.get("processed_by_username") or "администратор"
        processed_at = _format_dt(request.get("processed_at"))
        return (
            "✅ <b>КБ зачислены в Langame</b>\n\n"
            f"Заявка КБ: <code>{request_id}</code>\n\n"
            f"Гость: <b>{guest_name}</b>\n"
            f"Телефон: <code>{phone}</code>\n"
            f"Guest ID: <code>{guest_id}</code>\n"
            f"Club ID: <code>{club_id}</code>\n"
            f"Сумма: <b>{amount}</b> бонусов\n\n"
            "Статус: <b>зачислено</b>\n"
            f"Зачислил: <b>{_html(processed_by)}</b>\n"
            f"Дата зачисления: <b>{_html(processed_at)}</b>"
        )

    return (
        "💎 <b>Заявка на перевод КБ</b>\n\n"
        f"Заявка КБ: <code>{request_id}</code>\n\n"
        f"Гость: <b>{guest_name}</b>\n"
        f"Телефон: <code>{phone}</code>\n"
        f"Guest ID: <code>{guest_id}</code>\n"
        f"Club ID: <code>{club_id}</code>\n"
        f"Сумма к зачислению в Langame: <b>{amount}</b> бонусов\n\n"
        "Бонусы уже списаны с кошелька гостя в Cyber Bonus.\n"
        "После зачисления в Langame нажмите кнопку ниже."
    )


def _notify_admin_chat(
    guest: dict[str, Any], amount: int, redeem_request_id: int
) -> tuple[bool, int | None, str | None, str | None]:
    token = (CM_BONUS_BOT_TOKEN or "").strip()
    chat_id = get_cm_bonus_admin_chat_id_for_club(int(guest.get("club_id") or 0))
    if not token:
        return False, None, "CM_BONUS_BOT_TOKEN не заполнен", chat_id
    if not chat_id:
        return False, None, "В настройках клуба не заполнен ID Telegram-беседы для КБ", chat_id

    request = {
        "id": redeem_request_id,
        "club_id": guest.get("club_id"),
        "guest_id": guest.get("guest_id"),
        "guest_name": guest.get("fio"),
        "guest_phone": guest.get("phone"),
        "amount": amount,
        "status": "notified",
    }
    text = format_cm_bonus_redeem_message(request)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Бонусы зачислены",
                        "callback_data": f"cm_bonus_credited:{redeem_request_id}",
                    }
                ]
            ]
        },
    }
    try:
        client_kwargs: dict[str, Any] = {"timeout": 20.0}
        proxy_url = (CM_BONUS_PROXY_URL or TG_PROXY_URL or "").strip()
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        with httpx.Client(**client_kwargs) as client:
            response = client.post(url, json=payload)
        data = response.json()
        if response.status_code >= 400 or not data.get("ok"):
            return False, None, str(data), chat_id
        message_id = (data.get("result") or {}).get("message_id")
        return True, message_id, None, chat_id
    except Exception as e:
        return False, None, str(e), chat_id


def _redeem_notification_retry_delay(attempts: int) -> timedelta:
    """Back off persistent Telegram failures without abandoning the request."""
    if attempts <= 1:
        return timedelta(minutes=1)
    if attempts == 2:
        return timedelta(minutes=5)
    if attempts == 3:
        return timedelta(minutes=15)
    return timedelta(minutes=60)


def _claim_cm_bonus_redeem_notification(request_id: int) -> dict[str, Any] | None:
    """Atomically claim a new, failed or stale notification for delivery."""
    now = _utcnow()
    stale_before = now - timedelta(minutes=10)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                UPDATE cm_bonus_redeem_requests
                SET status = 'notify_retrying',
                    notify_attempts = notify_attempts + 1,
                    last_notify_attempt_at = %s,
                    next_notify_attempt_at = NULL
                WHERE id = %s
                  AND telegram_message_id IS NULL
                  AND (
                        status = 'created'
                     OR status = 'notify_failed'
                     OR (status = 'notify_retrying' AND last_notify_attempt_at < %s)
                  )
                """,
                (now, request_id, stale_before),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    finally:
        conn.close()

    return get_cm_bonus_redeem_request_by_id(request_id)


def notify_cm_bonus_redeem_request(request_id: int) -> dict[str, Any]:
    """Deliver one admin notification without touching the guest balance."""
    request = _claim_cm_bonus_redeem_notification(int(request_id))
    if not request:
        return {"ok": False, "request_id": int(request_id), "skipped": True}

    guest = {
        "club_id": request.get("club_id"),
        "guest_id": request.get("guest_id"),
        "fio": request.get("guest_name"),
        "phone": request.get("guest_phone"),
    }
    sent, message_id, error_text, chat_id = _notify_admin_chat(
        guest,
        int(request.get("amount") or 0),
        int(request_id),
    )
    attempts = int(request.get("notify_attempts") or 1)
    next_attempt_at = None if sent else _utcnow() + _redeem_notification_retry_delay(attempts)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                UPDATE cm_bonus_redeem_requests
                SET status = %s,
                    admin_chat_id = %s,
                    telegram_message_id = %s,
                    error_text = %s,
                    next_notify_attempt_at = %s
                WHERE id = %s
                  AND status = 'notify_retrying'
                """,
                (
                    "notified" if sent else "notify_failed",
                    str(chat_id or "") or None,
                    message_id,
                    error_text,
                    next_attempt_at,
                    request_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": sent,
        "request_id": int(request_id),
        "message_id": message_id,
        "admin_chat_id": chat_id,
        "error_text": error_text,
        "notify_attempts": attempts,
        "next_notify_attempt_at": next_attempt_at,
    }


def retry_failed_cm_bonus_redeem_notifications(limit: int = 50) -> dict[str, Any]:
    """Retry due notifications; stale in-flight rows are recovered after ten minutes."""
    now = _utcnow()
    stale_before = now - timedelta(minutes=10)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT id
                FROM cm_bonus_redeem_requests
                WHERE telegram_message_id IS NULL
                  AND (
                        (
                            status = 'created'
                            AND requested_at <= %s
                        )
                     OR (
                            status = 'notify_failed'
                            AND (next_notify_attempt_at IS NULL OR next_notify_attempt_at <= %s)
                        )
                     OR (
                            status = 'notify_retrying'
                            AND last_notify_attempt_at < %s
                        )
                  )
                ORDER BY COALESCE(next_notify_attempt_at, requested_at) ASC, id ASC
                LIMIT %s
                """,
                (now - timedelta(minutes=1), now, stale_before, max(1, min(int(limit), 500))),
            )
            request_ids = [int(row["id"]) for row in cursor.fetchall()]
    finally:
        conn.close()

    sent = 0
    failed = 0
    skipped = 0
    for request_id in request_ids:
        result = notify_cm_bonus_redeem_request(request_id)
        if result.get("skipped"):
            skipped += 1
        elif result.get("ok"):
            sent += 1
        else:
            failed += 1

    return {
        "selected": len(request_ids),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


def redeem_cm_bonuses(guest: dict[str, Any], amount: int | None = None) -> dict[str, Any]:
    """Withdraw guest КБ and notify admin chat for manual Langame credit."""
    guest_id = int(guest["guest_id"])
    club_id = int(guest["club_id"])

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            balance = _get_balance_for_update(cursor, guest_id, club_id)
            redeem_amount = int(amount or balance)
            if redeem_amount <= 0:
                raise ValueError("Нет бонусов для перевода")
            if redeem_amount > balance:
                raise ValueError("Недостаточно бонусов")

            cursor.execute(
                """
                INSERT INTO cm_bonus_redeem_requests (club_id, guest_id, amount, status, requested_at)
                VALUES (%s, %s, %s, 'created', %s)
                """,
                (club_id, guest_id, redeem_amount, _utcnow()),
            )
            redeem_request_id = cursor.lastrowid

            add_cm_bonus_transaction(
                cursor=cursor,
                guest_id=guest_id,
                club_id=club_id,
                amount=-redeem_amount,
                source_type="redeem_request",
                source_id=str(redeem_request_id),
                description="Перевод КБ на игровой баланс Langame",
                status="pending_admin_credit",
            )
        conn.commit()
    finally:
        conn.close()

    notification = notify_cm_bonus_redeem_request(redeem_request_id)
    notification_sent = bool(notification.get("ok"))
    error_text = notification.get("error_text")

    return {
        "ok": True,
        "amount": redeem_amount,
        "request_id": redeem_request_id,
        "notification_sent": notification_sent,
        "error_text": error_text,
        "balance_after": get_cm_bonus_balance(guest_id, club_id),
    }


def get_cm_bonus_redeem_history(guest_id: int, club_id: int, limit: int = 30):
    """Return guest КБ transfer requests with user-friendly status labels."""
    status_labels = {
        "created": "создана",
        "notify_retrying": "уведомляем администратора",
        "notified": "ожидает зачисления",
        "notify_failed": "ошибка уведомления",
        "credited": "зачислено",
        "cancelled": "отменена",
        "failed": "ошибка",
    }
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT id, amount, status, error_text, requested_at, processed_at
                FROM cm_bonus_redeem_requests
                WHERE club_id = %s AND guest_id = %s
                ORDER BY requested_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, limit),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        item = dict(row)
        status = str(item.get("status") or "created")
        item["status_label"] = status_labels.get(status, status)
        if status == "credited":
            item["status_class"] = "issued"
        elif status in {"notify_failed", "failed", "cancelled"}:
            item["status_class"] = "cancelled"
        else:
            item["status_class"] = "pending"
        result.append(item)
    return result


def mark_cm_bonus_redeem_credited_by_telegram(
    request_id: int,
    chat_id: str | int | None,
    telegram_id: int | None,
    username: str | None = None,
) -> dict[str, Any]:
    chat_id_str = str(chat_id or "").strip()

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT r.*,
                       g.fio AS guest_name,
                       g.phone AS guest_phone
                FROM cm_bonus_redeem_requests r
                LEFT JOIN guests g
                  ON g.guest_id = r.guest_id
                 AND g.club_id = r.club_id
                WHERE r.id = %s
                LIMIT 1
                FOR UPDATE
                """,
                (request_id,),
            )
            request = cursor.fetchone()
            if not request:
                return {"ok": False, "error": "not_found", "message": f"Заявка КБ #{request_id} не найдена."}

            stored_chat_id = str(request.get("admin_chat_id") or "").strip()
            if stored_chat_id and chat_id_str and stored_chat_id != chat_id_str:
                return {
                    "ok": False,
                    "error": "wrong_chat",
                    "message": "Эту заявку нельзя закрыть из этого чата.",
                }

            status = request.get("status") or "pending"
            if status == "credited":
                return {
                    "ok": True,
                    "already_done": True,
                    "request": request,
                    "message": f"Заявка КБ #{request_id} уже была отмечена как зачисленная.",
                }

            if status in {"cancelled", "failed"}:
                return {
                    "ok": False,
                    "error": "invalid_status",
                    "request": request,
                    "message": f"Заявку КБ #{request_id} нельзя закрыть в статусе {status}.",
                }

            processed_at = _utcnow()
            cursor.execute(
                """
                UPDATE cm_bonus_redeem_requests
                SET status = 'credited',
                    processed_at = %s,
                    processed_by_telegram_id = %s,
                    processed_by_username = %s,
                    error_text = NULL
                WHERE id = %s
                """,
                (processed_at, telegram_id, username, request_id),
            )
            cursor.execute(
                """
                UPDATE cm_bonus_transactions
                SET status = 'credited_to_langame'
                WHERE club_id = %s
                  AND guest_id = %s
                  AND source_type = 'redeem_request'
                  AND source_id = %s
                """,
                (request.get("club_id"), request.get("guest_id"), str(request_id)),
            )
        conn.commit()
    finally:
        conn.close()

    updated_request = get_cm_bonus_redeem_request_by_id(request_id)
    return {
        "ok": True,
        "request": updated_request,
        "message": f"КБ по заявке #{request_id} отмечены как зачисленные.",
    }
