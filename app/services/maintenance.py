from app.core import get_db_connection


GLOBAL_MAINTENANCE_CLUB_ID = 0


def _enabled(value) -> bool:
    try:
        return bool(int(value or 0))
    except (TypeError, ValueError):
        return False


def get_maintenance_overview() -> dict:
    """Return a fail-open snapshot for the admin page."""
    try:
        with get_db_connection() as db:
            with db.cursor() as cur:
                cur.execute("SELECT club_id, is_enabled FROM module_maintenance_settings")
                rows = cur.fetchall()
    except Exception:
        return {"global_enabled": False, "clubs": {}}

    states = {int(row["club_id"]): _enabled(row.get("is_enabled")) for row in rows}
    return {
        "global_enabled": states.pop(GLOBAL_MAINTENANCE_CLUB_ID, False),
        "clubs": states,
    }


def is_maintenance_enabled(club_id) -> bool:
    if club_id is None:
        return False
    try:
        club_id = int(club_id)
    except (TypeError, ValueError):
        return False

    try:
        with get_db_connection() as db:
            with db.cursor() as cur:
                cur.execute(
                    """
                    SELECT MAX(is_enabled) AS is_enabled
                    FROM module_maintenance_settings
                    WHERE club_id IN (%s, %s)
                    """,
                    (GLOBAL_MAINTENANCE_CLUB_ID, club_id),
                )
                row = cur.fetchone() or {}
        return _enabled(row.get("is_enabled"))
    except Exception:
        # A code deploy before the migration must not lock users out.
        return False


def set_global_maintenance(enabled: bool) -> None:
    set_club_maintenance(GLOBAL_MAINTENANCE_CLUB_ID, enabled)


def set_club_maintenance(club_id: int, enabled: bool) -> None:
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO module_maintenance_settings (club_id, is_enabled)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE is_enabled=VALUES(is_enabled)
                """,
                (int(club_id), 1 if enabled else 0),
            )
        db.commit()
