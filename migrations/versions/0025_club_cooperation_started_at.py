"""Remember the first successful initial guest sync (UTC start time)."""

revision = "0025_club_cooperation_started_at"


def upgrade(cursor) -> None:
    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clubs'
          AND COLUMN_NAME = 'cooperation_started_at'
        """)
    if not int((cursor.fetchone() or {}).get("cnt") or 0):
        cursor.execute("ALTER TABLE clubs ADD COLUMN cooperation_started_at DATETIME NULL")

    # Use only recorded successful initial guest loads, never guest registration
    # dates from LG. Leave unknown dates NULL and preserve already recorded dates.
    cursor.execute("""
        UPDATE clubs
        SET cooperation_started_at = (
            SELECT MIN(started_at)
            FROM admin_sync_logs
            WHERE admin_sync_logs.club_id = clubs.club_id
              AND script_name = 'guests'
              AND sync_mode = 'initial'
              AND status = 'success'
        )
        WHERE cooperation_started_at IS NULL
        """)
