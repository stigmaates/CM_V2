"""Track admin panel user last login."""

revision = "0004_admin_user_last_login"


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
    if not _column_exists(cursor, "users", "last_login_at"):
        cursor.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL AFTER created_at")
