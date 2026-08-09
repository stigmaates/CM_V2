"""Store CRM segment reasons and pulse handling state."""

revision = "0012_user_portrait_crm_reason"


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


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
    if _table_exists(cursor, "user_portrait") and not _column_exists(cursor, "user_portrait", "crm_reason"):
        cursor.execute("""
            ALTER TABLE user_portrait
            ADD COLUMN crm_reason VARCHAR(255) NULL AFTER crm_type
            """)

    if not _table_exists(cursor, "crm_status_changes"):
        return

    pulse_columns = [
        ("handled_at", "DATETIME NULL"),
        ("handled_reason", "VARCHAR(40) NULL"),
        ("handled_mailing_id", "INT NULL"),
        ("handled_giveaway_id", "INT NULL"),
    ]
    for column_name, definition in pulse_columns:
        if _column_exists(cursor, "crm_status_changes", column_name):
            continue
        cursor.execute(f"ALTER TABLE crm_status_changes ADD COLUMN {column_name} {definition} AFTER new_crm_type")
