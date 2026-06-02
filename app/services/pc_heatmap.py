from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core import get_db_connection

_pc_names_table_ready = False


def ensure_pc_names_table(cursor) -> None:
    """Create table for per-club PC names/order mapped to Langame session UUID."""
    global _pc_names_table_ready
    if _pc_names_table_ready:
        return

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS club_pc_names (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            uuid VARCHAR(100) NOT NULL,
            display_name VARCHAR(120) NULL,
            sort_order INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_club_pc_uuid (club_id, uuid),
            KEY idx_club_pc_order (club_id, sort_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _pc_names_table_ready = True


def _sync_recent_session_uuids(cursor, club_id: int) -> None:
    """Ensure every UUID used in the last year exists in club_pc_names."""
    cursor.execute(
        """
        SELECT DISTINCT uuid
        FROM guest_sessions
        WHERE club_id = %s
          AND uuid IS NOT NULL
          AND TRIM(uuid) <> ''
          AND date_start >= DATE_SUB(NOW(), INTERVAL 1 YEAR)
        ORDER BY uuid
        """,
        (club_id,),
    )
    rows = cursor.fetchall() or []

    for row in rows:
        uuid = (row.get("uuid") or "").strip()
        if not uuid:
            continue
        cursor.execute(
            """
            INSERT IGNORE INTO club_pc_names (club_id, uuid, display_name, sort_order)
            VALUES (%s, %s, NULL, 9999)
            """,
            (club_id, uuid),
        )

    cursor.execute(
        """
        SET @rn := 0
        """
    )
    cursor.execute(
        """
        UPDATE club_pc_names cpn
        JOIN (
            SELECT id, (@rn := @rn + 10) AS new_sort_order
            FROM club_pc_names
            WHERE club_id = %s
            ORDER BY sort_order, COALESCE(NULLIF(display_name, ''), uuid), uuid
        ) ordered ON ordered.id = cpn.id
        SET cpn.sort_order = ordered.new_sort_order
        WHERE cpn.club_id = %s
        """,
        (club_id, club_id),
    )


def get_pc_name_settings(club_id: int) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_pc_names_table(cursor)
            _sync_recent_session_uuids(cursor, club_id)
            cursor.execute(
                """
                SELECT uuid, display_name, sort_order
                FROM club_pc_names
                WHERE club_id = %s
                ORDER BY sort_order, COALESCE(NULLIF(display_name, ''), uuid), uuid
                """,
                (club_id,),
            )
            rows = cursor.fetchall() or []
        conn.commit()
        result = []
        for idx, row in enumerate(rows, start=1):
            uuid = row.get("uuid") or ""
            display_name = (row.get("display_name") or "").strip()
            result.append({
                "uuid": uuid,
                "display_name": display_name,
                "effective_name": display_name or f"ПК {idx}",
                "sort_order": int(row.get("sort_order") or idx * 10),
            })
        return result
    finally:
        conn.close()


def save_pc_name_settings(club_id: int, items: list[dict[str, Any]]) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_pc_names_table(cursor)
            _sync_recent_session_uuids(cursor, club_id)
            for idx, item in enumerate(items, start=1):
                uuid = (item.get("uuid") or "").strip()
                if not uuid:
                    continue
                display_name = (item.get("display_name") or "").strip() or None
                sort_order = int(item.get("sort_order") or idx * 10)
                cursor.execute(
                    """
                    INSERT INTO club_pc_names (club_id, uuid, display_name, sort_order)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        sort_order = VALUES(sort_order),
                        updated_at = NOW()
                    """,
                    (club_id, uuid, display_name, sort_order),
                )
        conn.commit()
    finally:
        conn.close()


def _level_for_value(value: float, max_value: float) -> int:
    if max_value <= 0 or value <= 0:
        return 0
    return max(1, min(5, round((value / max_value) * 5)))


def get_pc_hours_heatmap_stats(club_id: int, period_days: int = 30) -> dict[str, Any]:
    """Return PC heatmap: one tile per PC with total occupied hours for selected period."""
    if period_days not in (7, 30, 90):
        period_days = 30

    current_end = datetime.now()
    current_start = current_end - timedelta(days=period_days)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_pc_names_table(cursor)
            _sync_recent_session_uuids(cursor, club_id)
            cursor.execute(
                """
                SELECT
                    cpn.uuid,
                    cpn.display_name,
                    cpn.sort_order,
                    COALESCE(SUM(
                        GREATEST(
                            0,
                            TIMESTAMPDIFF(
                                MINUTE,
                                GREATEST(gs.date_start, %s),
                                LEAST(COALESCE(gs.date_stop, NOW()), %s)
                            )
                        )
                    ), 0) / 60 AS total_hours,
                    COUNT(gs.id) AS sessions_count
                FROM club_pc_names cpn
                LEFT JOIN guest_sessions gs
                  ON gs.club_id = cpn.club_id
                 AND gs.uuid = cpn.uuid
                 AND gs.date_start IS NOT NULL
                 AND gs.date_start < %s
                 AND COALESCE(gs.date_stop, NOW()) > %s
                WHERE cpn.club_id = %s
                GROUP BY cpn.uuid, cpn.display_name, cpn.sort_order
                ORDER BY cpn.sort_order, COALESCE(NULLIF(cpn.display_name, ''), cpn.uuid), cpn.uuid
                """,
                (current_start, current_end, current_end, current_start, club_id),
            )
            rows = cursor.fetchall() or []
        conn.commit()
    finally:
        conn.close()

    max_hours = max((float(row.get("total_hours") or 0) for row in rows), default=0)
    total_hours = sum(float(row.get("total_hours") or 0) for row in rows)
    total_sessions = sum(int(row.get("sessions_count") or 0) for row in rows)

    pcs = []
    for idx, row in enumerate(rows, start=1):
        raw_hours = float(row.get("total_hours") or 0)
        display_name = (row.get("display_name") or "").strip()
        label = display_name or f"ПК {idx}"
        pcs.append({
            "uuid": row.get("uuid"),
            "name": label,
            "display_name": display_name,
            "hours": round(raw_hours, 1),
            "hours_display": str(round(raw_hours, 1)).replace(".0", "").replace(".", ","),
            "sessions_count": int(row.get("sessions_count") or 0),
            "level": _level_for_value(raw_hours, max_hours),
        })

    peak_pc = max(pcs, key=lambda item: item["hours"], default=None)

    return {
        "period_days": period_days,
        "pcs": pcs,
        "max_hours": round(max_hours, 1),
        "total_hours": round(total_hours, 1),
        "total_hours_display": str(round(total_hours, 1)).replace(".0", "").replace(".", ","),
        "total_sessions": total_sessions,
        "peak": peak_pc or {"name": "—", "hours_display": "0", "sessions_count": 0},
        "debug": {"current_start": str(current_start), "current_end": str(current_end)},
    }
