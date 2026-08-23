from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core import get_db_connection
from app.services.cases import ensure_case_tables
from app.services.cm_bonuses import ensure_cm_bonus_tables
from app.services.prize_claims import ensure_prize_claim_tables
from app.services.wheel import ensure_token_tables, ensure_wheel_prize_bonus_columns


def _format_amount(amount: int, unit: str) -> str:
    prefix = "+" if amount > 0 else ""
    return f"{prefix}{amount} {unit}"


def _format_status(status: str | None, fallback: str = "ожидает выдачи") -> tuple[str, str]:
    if status == "issued":
        return "выдан", "issued"
    if status == "cancelled":
        return "отменён", "cancelled"
    if status in ("pending", "notified", "notify_failed", "notify_retrying"):
        return fallback, "pending"
    return fallback, "pending"


def _ledger_reward(
    row: dict[str, Any],
    *,
    kind: str,
    unit: str,
    icon: str,
    default_title: str,
) -> dict[str, Any] | None:
    amount = int(row.get("amount") or 0)
    if amount <= 0:
        return None

    description = (row.get("description") or "").strip()
    title = description or default_title
    if len(title) > 95:
        title = title[:92].rstrip() + "..."

    return {
        "kind": kind,
        "title": title,
        "subtitle": f"Баланс после: {int(row.get('balance_after') or 0)} {unit}",
        "amount_label": _format_amount(amount, unit),
        "status_label": "начислено",
        "status_class": "issued",
        "created_at": row.get("created_at"),
        "icon": icon,
        "image_url": None,
        "source_type": row.get("source_type"),
        "source_id": row.get("source_id"),
        "sort_id": int(row.get("id") or 0),
    }


def _case_reward(row: dict[str, Any]) -> dict[str, Any] | None:
    if int(row.get("bonus_amount") or 0) > 0 or int(row.get("token_amount") or 0) > 0:
        return None

    status_label, status_class = _format_status(row.get("claim_status"))
    title = row.get("name") or "Приз из кейса"
    case_name = row.get("case_name") or "Кейс"

    return {
        "kind": "case_prize",
        "title": title,
        "subtitle": case_name,
        "amount_label": "приз",
        "status_label": status_label,
        "status_class": status_class,
        "created_at": row.get("created_at"),
        "icon": "🎁",
        "image_url": row.get("image_url"),
        "source_type": "case_opening",
        "source_id": str(row.get("opening_id") or ""),
        "sort_id": int(row.get("opening_id") or 0),
    }


def _wheel_reward(row: dict[str, Any]) -> dict[str, Any] | None:
    if int(row.get("bonus_amount") or 0) > 0 or int(row.get("token_amount") or 0) > 0:
        return None

    status_label, status_class = _format_status(row.get("claim_status"))
    title = row.get("name") or "Приз колеса"
    subtitle = (row.get("description") or "Приз сохранён за тобой").strip()

    return {
        "kind": "wheel_prize",
        "title": title,
        "subtitle": subtitle,
        "amount_label": "приз",
        "status_label": status_label,
        "status_class": status_class,
        "created_at": row.get("created_at"),
        "icon": row.get("icon_emoji") or "🎁",
        "image_url": None,
        "source_type": "wheel_spin",
        "source_id": str(row.get("spin_id") or ""),
        "sort_id": int(row.get("spin_id") or 0),
    }


def _sort_key(item: dict[str, Any]) -> tuple[datetime, int]:
    created_at = item.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = datetime.min
    return created_at, int(item.get("sort_id") or 0)


def combine_guest_reward_history(
    *,
    token_rows: list[dict[str, Any]],
    bonus_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    wheel_rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    rewards: list[dict[str, Any]] = []

    for row in token_rows:
        item = _ledger_reward(row, kind="token", unit="жет.", icon="🪙", default_title="Начисление жетонов")
        if item:
            rewards.append(item)

    for row in bonus_rows:
        item = _ledger_reward(row, kind="bonus", unit="КБ", icon="💎", default_title="Начисление КБ")
        if item:
            rewards.append(item)

    for row in case_rows:
        item = _case_reward(row)
        if item:
            rewards.append(item)

    for row in wheel_rows:
        item = _wheel_reward(row)
        if item:
            rewards.append(item)

    rewards.sort(key=_sort_key, reverse=True)
    return rewards[:limit]


def get_guest_reward_history(guest_id: int, club_id: int, limit: int = 12) -> list[dict[str, Any]]:
    query_limit = max(limit * 3, 20)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_token_tables(cursor)
            ensure_cm_bonus_tables(cursor)
            ensure_case_tables(cursor)
            ensure_prize_claim_tables(cursor)
            ensure_wheel_prize_bonus_columns(cursor)

            cursor.execute(
                """
                SELECT id, amount, balance_after, source_type, source_id, description, created_at
                FROM guest_wheel_token_transactions
                WHERE club_id = %s
                  AND guest_id = %s
                  AND amount > 0
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, query_limit),
            )
            token_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT id, amount, balance_after, source_type, source_id, description, status, created_at
                FROM cm_bonus_transactions
                WHERE club_id = %s
                  AND guest_id = %s
                  AND amount > 0
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, query_limit),
            )
            bonus_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    o.id AS opening_id,
                    o.created_at,
                    cs.name AS case_name,
                    i.name,
                    i.image_url,
                    i.bonus_amount,
                    i.token_amount,
                    c.status AS claim_status
                FROM guest_case_openings o
                JOIN club_case_items i ON i.id = o.item_id
                JOIN club_cases cs ON cs.id = o.case_id
                LEFT JOIN guest_prize_claims c ON c.spin_id = -o.id
                WHERE o.club_id = %s
                  AND o.guest_id = %s
                  AND COALESCE(i.bonus_amount, 0) = 0
                  AND COALESCE(i.token_amount, 0) = 0
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT %s
                """,
                (club_id, guest_id, query_limit),
            )
            case_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    s.id AS spin_id,
                    s.created_at,
                    p.name,
                    p.description,
                    p.icon_emoji,
                    p.bonus_amount,
                    p.token_amount,
                    c.status AS claim_status
                FROM guest_wheel_spins s
                JOIN club_wheel_prizes p ON p.id = s.prize_id
                LEFT JOIN guest_prize_claims c ON c.spin_id = s.id
                WHERE s.club_id = %s
                  AND s.guest_id = %s
                  AND COALESCE(p.bonus_amount, 0) = 0
                  AND COALESCE(p.token_amount, 0) = 0
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT %s
                """,
                (club_id, guest_id, query_limit),
            )
            wheel_rows = cursor.fetchall()

        return combine_guest_reward_history(
            token_rows=token_rows,
            bonus_rows=bonus_rows,
            case_rows=case_rows,
            wheel_rows=wheel_rows,
            limit=limit,
        )
    finally:
        conn.close()
