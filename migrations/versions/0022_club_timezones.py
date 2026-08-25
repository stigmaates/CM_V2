"""Add an IANA timezone to each club for local schedules."""

revision = "0022_club_timezones"


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
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
    return int((cursor.fetchone() or {}).get("cnt") or 0) > 0


def upgrade(cursor) -> None:
    if not _column_exists(cursor, "clubs", "timezone"):
        cursor.execute("""
            ALTER TABLE clubs
            ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow' AFTER name
            """)
