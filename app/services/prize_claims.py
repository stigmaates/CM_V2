from __future__ import annotations

from datetime import datetime
from typing import Any
from html import escape

import httpx

from app.config import BOT_TOKEN, CM_BONUS_BOT_TOKEN, CM_BONUS_PROXY_URL, TG_PROXY_URL
from app.core import get_db_connection
from app.services.cm_bonuses import get_cm_bonus_admin_chat_id_for_club


_prize_claim_tables_ready = False


STATUS_LABELS = {
    "pending": "ожидает выдачи",
    "notified": "ожидает выдачи",
    "notify_failed": "ожидает выдачи, уведомление не ушло",
    "issued": "выдан",
    "cancelled": "отменён",
}


def ensure_prize_claim_tables(cursor) -> None:
    """Create manual wheel prize claim table lazily."""
    global _prize_claim_tables_ready
    if _prize_claim_tables_ready:
        return

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_prize_claims (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            spin_id INT NOT NULL,
            prize_id INT NOT NULL,
            prize_name VARCHAR(255) NOT NULL,
            prize_description TEXT NULL,
            prize_image_url TEXT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            admin_chat_id VARCHAR(80) NULL,
            telegram_message_id BIGINT NULL,
            notify_error TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notified_at DATETIME NULL,
            issued_at DATETIME NULL,
            issued_by_telegram_id BIGINT NULL,
            issued_by_username VARCHAR(255) NULL,
            cancelled_at DATETIME NULL,
            cancelled_by_telegram_id BIGINT NULL,
            cancel_reason VARCHAR(255) NULL,
            KEY idx_prize_claims_club_status (club_id, status),
            KEY idx_prize_claims_guest (club_id, guest_id, created_at),
            KEY idx_prize_claims_spin (spin_id),
            UNIQUE KEY uq_prize_claim_spin (spin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _prize_claim_tables_ready = True


def _format_phone(phone: str | None) -> str:
    if not phone:
        return "не указан"
    value = str(phone).strip()
    if len(value) == 10 and value.isdigit():
        return "+7" + value
    return value


def _status_label(status: str | None) -> str:
    return STATUS_LABELS.get((status or "").strip(), status or "ожидает выдачи")




def _html(value: Any) -> str:
    return escape(str(value or ""), quote=False)


def _format_dt(value: Any) -> str:
    if not value:
        return "не указано"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except AttributeError:
        return str(value)


def format_prize_claim_message(claim: dict[str, Any], issued: bool = False) -> str:
    claim_id = claim.get("id")
    club_id = claim.get("club_id")
    guest_name = _html(claim.get("guest_name") or "Гость")
    phone = _html(_format_phone(claim.get("guest_phone")))
    guest_id = _html(claim.get("guest_id"))
    prize_name = _html(claim.get("prize_name") or "Приз")
    prize_description = (claim.get("prize_description") or "").strip()
    description_line = f"Описание: <i>{_html(prize_description)}</i>\n" if prize_description else ""

    status = claim.get("status") or "pending"
    if issued or status == "issued":
        issued_by = claim.get("issued_by_username") or "администратор"
        issued_at = _format_dt(claim.get("issued_at"))
        return (
            "✅ <b>Приз выдан</b>\n\n"
            f"ID заявки: <code>{claim_id}</code>\n\n"
            f"Гость: <b>{guest_name}</b>\n"
            f"Телефон: <code>{phone}</code>\n"
            f"Guest ID: <code>{guest_id}</code>\n"
            f"Club ID: <code>{_html(club_id)}</code>\n\n"
            f"Приз: <b>{prize_name}</b>\n"
            f"{description_line}"
            "Статус: <b>выдан</b>\n"
            f"Выдал: <b>{_html(issued_by)}</b>\n"
            f"Дата выдачи: <b>{_html(issued_at)}</b>"
        )

    return (
        "🎁 <b>Заявка на выдачу приза</b>\n\n"
        f"ID заявки: <code>{claim_id}</code>\n\n"
        f"Гость: <b>{guest_name}</b>\n"
        f"Телефон: <code>{phone}</code>\n"
        f"Guest ID: <code>{guest_id}</code>\n"
        f"Club ID: <code>{_html(club_id)}</code>\n\n"
        f"Приз: <b>{prize_name}</b>\n"
        f"{description_line}"
        "Статус: <b>ожидает выдачи</b>\n\n"
        "После выдачи нажмите кнопку ниже."
    )

def create_prize_claim(cursor, guest_id: int, club_id: int, spin_id: int, prize: dict[str, Any]) -> int | None:
    """Create a manual issue task for a wheel prize. Returns claim id.

    КБ-prizes are credited automatically and should not create claims.
    """
    if not prize:
        return None

    bonus_amount = int(prize.get("bonus_amount") or 0)
    if bonus_amount > 0:
        return None

    prize_id = int(prize.get("id") or 0)
    prize_name = (prize.get("name") or "Приз колеса").strip()
    if not prize_id or not prize_name:
        return None

    ensure_prize_claim_tables(cursor)
    cursor.execute(
        """
        INSERT IGNORE INTO guest_prize_claims (
            club_id,
            guest_id,
            spin_id,
            prize_id,
            prize_name,
            prize_description,
            prize_image_url,
            status,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
        """,
        (
            club_id,
            guest_id,
            spin_id,
            prize_id,
            prize_name,
            prize.get("description"),
            prize.get("image_url"),
            datetime.utcnow(),
        ),
    )

    if cursor.lastrowid:
        return int(cursor.lastrowid)

    cursor.execute(
        """
        SELECT id
        FROM guest_prize_claims
        WHERE spin_id = %s
        LIMIT 1
        """,
        (spin_id,),
    )
    row = cursor.fetchone() or {}
    return int(row["id"]) if row.get("id") else None


def get_prize_claim_by_id(claim_id: int) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                SELECT c.*,
                       g.fio AS guest_name,
                       g.phone AS guest_phone
                FROM guest_prize_claims c
                LEFT JOIN guests g
                  ON g.guest_id = c.guest_id
                 AND g.club_id = c.club_id
                WHERE c.id = %s
                LIMIT 1
                """,
                (claim_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_prize_claim_by_spin_id(spin_id: int) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                SELECT *
                FROM guest_prize_claims
                WHERE spin_id = %s
                LIMIT 1
                """,
                (spin_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def serialize_prize_claim(claim: dict[str, Any] | None) -> dict[str, Any] | None:
    if not claim:
        return None
    status = claim.get("status") or "pending"
    return {
        "id": claim.get("id"),
        "status": status,
        "status_label": _status_label(status),
        "issued_at": claim.get("issued_at").isoformat() if claim.get("issued_at") else None,
        "cancelled_at": claim.get("cancelled_at").isoformat() if claim.get("cancelled_at") else None,
    }


def _notify_claim_admin_chat(claim: dict[str, Any]) -> tuple[bool, int | None, str | None, str | None]:
    # Prize messages are sent by the admin bot.
    # The same admin bot must also run as a separate polling service
    # and handle inline button callbacks.
    token = (CM_BONUS_BOT_TOKEN or "").strip()
    club_id = int(claim.get("club_id") or 0)
    chat_id = get_cm_bonus_admin_chat_id_for_club(club_id)

    if not token:
        return False, None, "Не заполнен CM_BONUS_BOT_TOKEN", chat_id
    if not chat_id:
        return False, None, "В настройках клуба не заполнен ID Telegram-беседы для заявок", chat_id

    claim_id = claim.get("id")
    text = format_prize_claim_message(claim)

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
                        "text": "✅ Приз выдан",
                        "callback_data": f"prize_claim_issued:{claim_id}",
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
        message_id = ((data.get("result") or {}).get("message_id"))
        return True, message_id, None, chat_id
    except Exception as e:
        return False, None, str(e), chat_id


def notify_prize_claim_admin_chat(claim_id: int) -> dict[str, Any]:
    claim = get_prize_claim_by_id(claim_id)
    if not claim:
        return {"ok": False, "error": "claim_not_found"}

    sent, message_id, error_text, chat_id = _notify_claim_admin_chat(claim)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                UPDATE guest_prize_claims
                SET status = %s,
                    admin_chat_id = %s,
                    telegram_message_id = %s,
                    notify_error = %s,
                    notified_at = %s
                WHERE id = %s
                  AND status IN ('pending', 'notified', 'notify_failed')
                """,
                (
                    "notified" if sent else "notify_failed",
                    str(chat_id or "") or None,
                    message_id,
                    error_text,
                    datetime.utcnow(),
                    claim_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": sent,
        "claim_id": claim_id,
        "message_id": message_id,
        "admin_chat_id": chat_id,
        "error_text": error_text,
    }


def mark_prize_claim_issued_by_telegram(
    claim_id: int,
    chat_id: str | int | None,
    telegram_id: int | None,
    username: str | None = None,
) -> dict[str, Any]:
    chat_id_str = str(chat_id or "").strip()

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                SELECT c.*,
                       g.fio AS guest_name,
                       g.phone AS guest_phone
                FROM guest_prize_claims c
                LEFT JOIN guests g
                  ON g.guest_id = c.guest_id
                 AND g.club_id = c.club_id
                WHERE c.id = %s
                LIMIT 1
                FOR UPDATE
                """,
                (claim_id,),
            )
            claim = cursor.fetchone()
            if not claim:
                return {"ok": False, "error": "not_found", "message": f"Заявка #{claim_id} не найдена."}

            stored_chat_id = str(claim.get("admin_chat_id") or "").strip()
            if stored_chat_id and chat_id_str and stored_chat_id != chat_id_str:
                return {
                    "ok": False,
                    "error": "wrong_chat",
                    "message": "Эту заявку нельзя закрыть из этого чата.",
                }

            status = claim.get("status") or "pending"
            if status == "issued":
                return {
                    "ok": True,
                    "already_done": True,
                    "claim": claim,
                    "message": f"Заявка #{claim_id} уже была отмечена как выданная.",
                }
            if status == "cancelled":
                return {
                    "ok": False,
                    "error": "cancelled",
                    "claim": claim,
                    "message": f"Заявка #{claim_id} отменена, выдать её нельзя.",
                }

            cursor.execute(
                """
                UPDATE guest_prize_claims
                SET status = 'issued',
                    issued_at = %s,
                    issued_by_telegram_id = %s,
                    issued_by_username = %s
                WHERE id = %s
                """,
                (datetime.utcnow(), telegram_id, username, claim_id),
            )
        conn.commit()
    finally:
        conn.close()

    updated_claim = get_prize_claim_by_id(claim_id)
    return {
        "ok": True,
        "claim": updated_claim,
        "message": f"Приз #{claim_id} отмечен как выдан.",
    }


def mark_prize_claim_issued_by_owner(claim_id: int, club_id: int, user_id: int | None = None) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                UPDATE guest_prize_claims
                SET status = 'issued',
                    issued_at = %s,
                    issued_by_username = %s
                WHERE id = %s
                  AND club_id = %s
                  AND status <> 'cancelled'
                """,
                (datetime.utcnow(), f"owner:{user_id}" if user_id else "owner", claim_id, club_id),
            )
            affected = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return {"ok": affected > 0, "affected": affected}


def cancel_prize_claim_by_owner(claim_id: int, club_id: int, reason: str | None = None, user_id: int | None = None) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                UPDATE guest_prize_claims
                SET status = 'cancelled',
                    cancelled_at = %s,
                    cancelled_by_telegram_id = NULL,
                    cancel_reason = %s,
                    issued_at = NULL
                WHERE id = %s
                  AND club_id = %s
                  AND status <> 'issued'
                """,
                (datetime.utcnow(), reason or f"cancelled_by_owner:{user_id}" if user_id else reason, claim_id, club_id),
            )
            affected = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return {"ok": affected > 0, "affected": affected}


def get_prize_claims_for_owner(club_id: int, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    status = (status or "").strip()
    params: list[Any] = [club_id]
    where_status = ""
    if status and status != "all":
        where_status = " AND c.status = %s"
        params.append(status)
    params.append(limit)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                f"""
                SELECT c.*,
                       g.fio AS guest_name,
                       g.phone AS guest_phone
                FROM guest_prize_claims c
                LEFT JOIN guests g
                  ON g.guest_id = c.guest_id
                 AND g.club_id = c.club_id
                WHERE c.club_id = %s
                {where_status}
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
            for row in rows:
                row["status_label"] = _status_label(row.get("status"))
            return rows
    finally:
        conn.close()
