from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Tuple

from app.services.mailing import AUTO_MAILING_DEFAULTS

CRM_STATUS_META = {
    "top": {"label": "Лучшие", "score": 6},
    "base": {"label": "База", "score": 5},
    "rare": {"label": "Редкие", "score": 4},
    "risk": {"label": "Риск", "score": 3},
    "lost": {"label": "Потерянные", "score": 2},
    "dead": {"label": "Давно без визита", "score": 1},
    "no_visits": {"label": "Без визитов", "score": 0},
}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _status_label(status: str | None) -> str:
    if not status:
        return "Без статуса"
    return CRM_STATUS_META.get(status, {}).get("label", status)


def _status_score(status: str | None) -> int:
    if not status:
        return -1
    return int(CRM_STATUS_META.get(status, {}).get("score", -1))


def _transition_direction(old_status: str | None, new_status: str | None) -> str:
    old_score = _status_score(old_status)
    new_score = _status_score(new_status)
    if new_score > old_score:
        return "up"
    if new_score < old_score:
        return "down"
    return "same"


def _first_name(fio: str | None) -> str:
    parts = (fio or "").strip().split()
    if not parts:
        return ""
    if len(parts) >= 2 and parts[0].lower().endswith(
        ("ов", "ова", "ев", "ева", "ин", "ина", "ский", "ская", "цкий", "цкая")
    ):
        return parts[1]
    return parts[0]


def _auto_mailing_title(code: str | None) -> str:
    if not code:
        return "авторассылка"
    return AUTO_MAILING_DEFAULTS.get(code, {}).get("title") or code


def _auto_mailing_code_expr(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'auto_mailing_logs'
              AND COLUMN_NAME IN ('automation_code', 'auto_mailing_code')
            """)
        columns = {row.get("COLUMN_NAME") for row in cur.fetchall() or []}
    if "automation_code" in columns:
        return "aml.automation_code"
    if "auto_mailing_code" in columns:
        return "aml.auto_mailing_code"
    return None


def ensure_crm_status_changes_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crm_status_changes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                guest_id INT NOT NULL,
                old_crm_type VARCHAR(40) NULL,
                new_crm_type VARCHAR(40) NOT NULL,
                changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_crm_status_changes_club_changed (club_id, changed_at),
                KEY idx_crm_status_changes_guest (club_id, guest_id, changed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)


def record_crm_status_changes(conn, records: Iterable[Dict[str, Any]]) -> int:
    records = list(records)
    if not records:
        return 0

    ensure_crm_status_changes_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT club_id, guest_id, crm_type FROM user_portrait")
        current = {
            (int(row["club_id"]), int(row["guest_id"])): row.get("crm_type")
            for row in cur.fetchall()
            if row.get("club_id") is not None and row.get("guest_id") is not None
        }

        changes = []
        for record in records:
            key = (int(record["club_id"]), int(record["guest_id"]))
            old_status = current.get(key)
            new_status = record.get("crm_type")
            if old_status is None or not new_status or old_status == new_status:
                continue
            changes.append((key[0], key[1], old_status, new_status))

        if changes:
            cur.executemany(
                """
                INSERT INTO crm_status_changes (club_id, guest_id, old_crm_type, new_crm_type)
                VALUES (%s, %s, %s, %s)
                """,
                changes,
            )
        return len(changes)


def get_crm_pulse_groups(conn, club_id: int) -> List[Dict[str, Any]]:
    ensure_crm_status_changes_table(conn)
    auto_code_expr = _auto_mailing_code_expr(conn)
    auto_select = "NULL"
    if auto_code_expr:
        auto_select = f"""
            (
                SELECT {auto_code_expr}
                FROM auto_mailing_logs aml
                WHERE aml.club_id = c.club_id
                  AND aml.guest_id = c.guest_id
                  AND aml.created_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                ORDER BY aml.created_at DESC
                LIMIT 1
            )
        """

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                c.id,
                c.club_id,
                c.guest_id,
                c.old_crm_type,
                c.new_crm_type,
                c.changed_at,
                g.fio,
                g.phone,
                g.telegram_id,
                up.visits_7d,
                up.visits_30d,
                up.visits_90d,
                up.days_since_last_visit,
                {auto_select} AS recent_auto_mailing_code
            FROM crm_status_changes c
            JOIN (
                SELECT club_id, guest_id, MAX(id) AS latest_id
                FROM crm_status_changes
                WHERE club_id = %s
                  AND changed_at >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                GROUP BY club_id, guest_id
            ) latest
              ON latest.latest_id = c.id
            LEFT JOIN guests g
              ON g.club_id = c.club_id
             AND g.guest_id = c.guest_id
            LEFT JOIN user_portrait up
              ON up.club_id = c.club_id
             AND up.guest_id = c.guest_id
            ORDER BY c.changed_at DESC
            LIMIT 500
            """,
            (club_id,),
        )
        rows = cur.fetchall()

    groups_by_key: Dict[Tuple[str | None, str | None], Dict[str, Any]] = {}
    for row in rows:
        old_status = row.get("old_crm_type")
        new_status = row.get("new_crm_type")
        key = (old_status, new_status)
        group = groups_by_key.setdefault(
            key,
            {
                "key": f"{old_status or 'none'}__{new_status or 'none'}",
                "old_status": old_status,
                "new_status": new_status,
                "old_label": _status_label(old_status),
                "new_label": _status_label(new_status),
                "direction": _transition_direction(old_status, new_status),
                "guests": [],
                "guest_ids": [],
                "total_count": 0,
                "telegram_count": 0,
                "recent_auto_count": 0,
            },
        )

        auto_code = row.get("recent_auto_mailing_code")
        guest = {
            "guest_id": int(row.get("guest_id") or 0),
            "fio": row.get("fio") or "",
            "first_name": _first_name(row.get("fio")),
            "phone": row.get("phone") or "",
            "has_telegram": bool(row.get("telegram_id")),
            "changed_at": _json_value(row.get("changed_at")),
            "visits_7d": int(row.get("visits_7d") or 0),
            "visits_30d": int(row.get("visits_30d") or 0),
            "visits_90d": int(row.get("visits_90d") or 0),
            "days_since_last_visit": row.get("days_since_last_visit"),
            "recent_auto_mailing_code": auto_code,
            "recent_auto_mailing_title": _auto_mailing_title(auto_code) if auto_code else None,
        }
        group["guests"].append(guest)
        group["guest_ids"].append(guest["guest_id"])
        group["total_count"] += 1
        if guest["has_telegram"]:
            group["telegram_count"] += 1
        if auto_code:
            group["recent_auto_count"] += 1

    groups = list(groups_by_key.values())
    direction_order = {"up": 0, "down": 1, "same": 2}
    groups.sort(key=lambda item: (direction_order.get(item["direction"], 9), -item["total_count"], item["new_label"]))
    return groups
