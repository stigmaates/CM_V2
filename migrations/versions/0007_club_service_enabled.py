"""Add per-club service availability flag."""

revision = "0007_club_service_enabled"


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
    if not _column_exists(cursor, "clubs", "service_enabled"):
        cursor.execute("""
            ALTER TABLE clubs
            ADD COLUMN service_enabled TINYINT(1) NOT NULL DEFAULT 1 AFTER owner_id
            """)
