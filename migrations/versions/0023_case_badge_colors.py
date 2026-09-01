"""Allow owners to choose a color for each case badge."""

revision = "0023_case_badge_colors"


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
    if not _column_exists(cursor, "club_cases", "badge_color"):
        cursor.execute("""
            ALTER TABLE club_cases
            ADD COLUMN badge_color VARCHAR(7) NOT NULL DEFAULT '#8F5BFF' AFTER badge_label
            """)
