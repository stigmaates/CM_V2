"""Add club-scoped valuable case drops setting."""

revision = "0014_valuable_drops_club_scope"


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
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def upgrade(cursor) -> None:
    if not _column_exists(cursor, "club_wheel_settings", "show_only_own_valuable_drops"):
        cursor.execute("""
            ALTER TABLE club_wheel_settings
            ADD COLUMN show_only_own_valuable_drops TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled
            """)
