"""Add a club-local send window to each auto mailing."""

revision = "0046_auto_mailing_send_windows"


def _column_exists(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE()
          AND TABLE_NAME='auto_mailing_settings'
          AND COLUMN_NAME=%s
        """,
        (column_name,),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def upgrade(cursor) -> None:
    if not _column_exists(cursor, "send_start_time"):
        cursor.execute(
            """
            ALTER TABLE auto_mailing_settings
            ADD COLUMN send_start_time TIME NOT NULL DEFAULT '10:00:00' AFTER repeat_after_days
            """
        )
    if not _column_exists(cursor, "send_end_time"):
        cursor.execute(
            """
            ALTER TABLE auto_mailing_settings
            ADD COLUMN send_end_time TIME NOT NULL DEFAULT '22:30:00' AFTER send_start_time
            """
        )
