from __future__ import annotations

import re
from typing import Any

from app.core import get_db_connection

PHONE_NORMALIZED_SQL = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(phone, ''), '+', ''), "
    "' ', ''), '-', ''), '(', ''), ')', ''), '.', '')"
)


def _phone_variants(raw_phone: str) -> list[str]:
    digits = re.sub(r"\D+", "", str(raw_phone or ""))
    if not digits:
        return []

    variants = {digits}
    if len(digits) == 10:
        variants.add("7" + digits)
        variants.add("8" + digits)
    if len(digits) == 11 and digits.startswith("8"):
        variants.add("7" + digits[1:])
        variants.add(digits[1:])
    if len(digits) == 11 and digits.startswith("7"):
        variants.add("8" + digits[1:])
        variants.add(digits[1:])
    return sorted(variants)


def _rows_or_empty(cursor, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    try:
        cursor.execute(sql, params)
        return cursor.fetchall() or []
    except Exception:
        return []


def _one_or_none(cursor, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    try:
        cursor.execute(sql, params)
        return cursor.fetchone()
    except Exception:
        return None


def _fetch_guest(cursor, *, club_id: int, phone: str) -> dict[str, Any] | None:
    variants = _phone_variants(phone)
    if not variants:
        return None

    placeholders = ", ".join(["%s"] * len(variants))
    cursor.execute(
        f"""
        SELECT guest_id, club_id, phone, fio, telegram_id
        FROM guests
        WHERE club_id = %s
          AND {PHONE_NORMALIZED_SQL} IN ({placeholders})
        ORDER BY
            CASE WHEN telegram_id IS NULL OR TRIM(CAST(telegram_id AS CHAR)) = '' THEN 1 ELSE 0 END,
            guest_id DESC
        LIMIT 1
        """,
        (club_id, *variants),
    )
    return cursor.fetchone()


def _balance_value(row: dict[str, Any] | None) -> int:
    if not row:
        return 0
    return int(row.get("balance") or 0)


def _source_label(source_type: str | None) -> str:
    labels = {
        "manual": "Ручное начисление",
        "wheel_prize": "Приз колеса",
        "case_prize": "Приз кейса",
        "case_open": "Открытие кейса",
        "mission": "Награда за задание",
        "mission_reward": "Награда за задание",
        "streak": "Стрик посещений",
        "welcome_token": "Первый вход в Telegram",
        "redeem_request": "Перевод КБ на игровой баланс",
        "auto_mailing": "Авторассылка",
        "bonus_giveaway": "Раздача КБ",
    }
    return labels.get(str(source_type or ""), str(source_type or "Операция"))


def _redeem_status_label(status: str | None) -> str:
    labels = {
        "created": "создана",
        "notified": "ожидает зачисления",
        "notify_failed": "не удалось отправить уведомление",
        "credited": "зачислено",
        "cancelled": "отменена",
        "failed": "ошибка",
    }
    return labels.get(str(status or ""), str(status or "создана"))


def _decorate_transactions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        item["reason"] = item.get("description") or _source_label(item.get("source_type"))
        result.append(item)
    return result


def _decorate_redeem_requests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        item["status_label"] = _redeem_status_label(item.get("status"))
        result.append(item)
    return result


def get_reception_guest_lookup(*, club_id: int, phone: str, limit: int = 30) -> dict[str, Any]:
    """Read-only guest support lookup for club reception staff."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guest = _fetch_guest(cursor, club_id=club_id, phone=phone)
            if not guest:
                return {"found": False, "query": phone}

            guest_id = int(guest["guest_id"])
            bonus_balance = _balance_value(
                _one_or_none(
                    cursor,
                    """
                SELECT balance
                FROM cm_bonus_balances
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                    (club_id, guest_id),
                )
            )
            token_balance = _balance_value(
                _one_or_none(
                    cursor,
                    """
                SELECT balance
                FROM guest_wheel_token_balances
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                    (club_id, guest_id),
                )
            )
            bonus_transactions = _rows_or_empty(
                cursor,
                """
                SELECT id, amount, balance_after, source_type, source_id, description, status, created_at
                FROM cm_bonus_transactions
                WHERE club_id = %s AND guest_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, int(limit)),
            )
            token_transactions = _rows_or_empty(
                cursor,
                """
                SELECT id, amount, balance_after, source_type, source_id, description, created_at
                FROM guest_wheel_token_transactions
                WHERE club_id = %s AND guest_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, int(limit)),
            )
            redeem_requests = _rows_or_empty(
                cursor,
                """
                SELECT id, amount, status, error_text, requested_at, processed_at,
                       processed_by_username
                FROM cm_bonus_redeem_requests
                WHERE club_id = %s AND guest_id = %s
                ORDER BY requested_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, int(limit)),
            )

        return {
            "found": True,
            "query": phone,
            "guest": {
                **guest,
                "has_telegram": bool(guest.get("telegram_id")),
                "bonus_balance": bonus_balance,
                "token_balance": token_balance,
            },
            "bonus_transactions": _decorate_transactions(bonus_transactions),
            "token_transactions": _decorate_transactions(token_transactions),
            "redeem_requests": _decorate_redeem_requests(redeem_requests),
        }
    finally:
        conn.close()
