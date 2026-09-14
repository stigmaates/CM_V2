"""Track asynchronous monthly report generation failures."""

revision = "0035_monthly_report_async"


def _column_exists(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE()
          AND TABLE_NAME='monthly_reports'
          AND COLUMN_NAME=%s
        """,
        (column_name,),
    )
    return int((cursor.fetchone() or {}).get("cnt") or 0) > 0


def upgrade(cursor) -> None:
    if not _column_exists(cursor, "error_message"):
        cursor.execute("ALTER TABLE monthly_reports ADD COLUMN error_message TEXT NULL AFTER status")
