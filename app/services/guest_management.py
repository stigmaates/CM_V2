from __future__ import annotations

import uuid
from typing import Any

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.reception import get_reception_guest_lookup
from app.services.wheel import add_guest_token_transaction


def _guest_exists(cursor, *, club_id: int, guest_id: int) -> bool:
    cursor.execute(
        """
        SELECT guest_id
        FROM guests
        WHERE club_id = %s AND guest_id = %s
        LIMIT 1
        """,
        (club_id, guest_id),
    )
    return bool(cursor.fetchone())


def get_guest_ban_status(*, club_id: int, guest_id: int) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    SELECT is_banned, reason, banned_by_user_id, banned_at, unbanned_at, updated_at
                    FROM guest_module_bans
                    WHERE club_id = %s AND guest_id = %s
                    LIMIT 1
                    """,
                    (club_id, guest_id),
                )
                row = cursor.fetchone() or {}
            except Exception as exc:
                if getattr(exc, "args", [None])[0] == 1146:
                    return {"is_banned": False}
                raise
        return {
            "is_banned": bool(row.get("is_banned")),
            "reason": row.get("reason"),
            "banned_by_user_id": row.get("banned_by_user_id"),
            "banned_at": row.get("banned_at"),
            "unbanned_at": row.get("unbanned_at"),
            "updated_at": row.get("updated_at"),
        }
    finally:
        conn.close()


def is_guest_module_banned(*, club_id: int, guest_id: int) -> bool:
    return bool(get_guest_ban_status(club_id=club_id, guest_id=guest_id).get("is_banned"))


def get_owner_guest_lookup(*, club_id: int, phone: str, limit: int = 50) -> dict[str, Any]:
    lookup = get_reception_guest_lookup(club_id=club_id, phone=phone, limit=limit)
    if not lookup.get("found"):
        return lookup

    guest = lookup["guest"]
    guest.update(
        get_guest_ban_status(
            club_id=int(club_id),
            guest_id=int(guest["guest_id"]),
        )
    )
    return lookup


def adjust_guest_balance(
    *,
    club_id: int,
    guest_id: int,
    balance_type: str,
    amount: int,
    actor_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    if balance_type not in {"cm_bonus", "tokens"}:
        raise ValueError("Неизвестный тип баланса")
    amount = int(amount or 0)
    if amount == 0:
        raise ValueError("Сумма изменения не может быть равна нулю")
    if abs(amount) > (100_000 if balance_type == "cm_bonus" else 10_000):
        raise ValueError("Слишком большая сумма ручной корректировки")

    clean_reason = (reason or "").strip()
    if len(clean_reason) > 255:
        raise ValueError("Причина корректировки не должна быть длиннее 255 символов")
    action_label = "начисление" if amount > 0 else "списание"
    currency_label = "КБ" if balance_type == "cm_bonus" else "жетонов"
    description = clean_reason or f"Ручное {action_label} {currency_label} владельцем"
    source_id = f"owner:{actor_user_id}:{uuid.uuid4().hex}"

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not _guest_exists(cursor, club_id=club_id, guest_id=guest_id):
                raise ValueError("Гость не найден в текущем клубе")

            if balance_type == "cm_bonus":
                ensure_cm_bonus_tables(cursor)
                changed = add_cm_bonus_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=amount,
                    source_type="owner_manual",
                    source_id=source_id,
                    description=description,
                    status="done",
                )
            else:
                changed = add_guest_token_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=amount,
                    source_type="owner_manual",
                    source_id=source_id,
                    description=description,
                )
        conn.commit()
        return {
            "changed": bool(changed),
            "balance_type": balance_type,
            "amount": amount,
            "description": description,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_guest_module_ban(
    *,
    club_id: int,
    guest_id: int,
    is_banned: bool,
    actor_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    clean_reason = (reason or "").strip()
    if len(clean_reason) > 255:
        raise ValueError("Причина блокировки не должна быть длиннее 255 символов")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not _guest_exists(cursor, club_id=club_id, guest_id=guest_id):
                raise ValueError("Гость не найден в текущем клубе")
            cursor.execute(
                """
                INSERT INTO guest_module_bans (
                    club_id,
                    guest_id,
                    is_banned,
                    reason,
                    banned_by_user_id,
                    banned_at,
                    unbanned_at
                )
                VALUES (%s, %s, %s, %s, %s, IF(%s = 1, NOW(), NULL), IF(%s = 0, NOW(), NULL))
                ON DUPLICATE KEY UPDATE
                    is_banned = VALUES(is_banned),
                    reason = VALUES(reason),
                    banned_by_user_id = VALUES(banned_by_user_id),
                    banned_at = IF(VALUES(is_banned) = 1, NOW(), banned_at),
                    unbanned_at = IF(VALUES(is_banned) = 0, NOW(), NULL)
                """,
                (
                    club_id,
                    guest_id,
                    int(bool(is_banned)),
                    clean_reason or None,
                    actor_user_id,
                    int(bool(is_banned)),
                    int(bool(is_banned)),
                ),
            )
        conn.commit()
        return {"is_banned": bool(is_banned), "reason": clean_reason or None}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
