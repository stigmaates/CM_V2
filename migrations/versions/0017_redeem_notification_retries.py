"""Add a persistent retry queue for failed КБ redeem notifications."""

revision = "0017_redeem_notification_retries"


def _column_exists(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'cm_bonus_redeem_requests'
          AND COLUMN_NAME = %s
        """,
        (column_name,),
    )
    return int((cursor.fetchone() or {}).get("cnt") or 0) > 0


def _index_exists(cursor, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'cm_bonus_redeem_requests'
          AND INDEX_NAME = %s
        """,
        (index_name,),
    )
    return int((cursor.fetchone() or {}).get("cnt") or 0) > 0


def upgrade(cursor) -> None:
    columns = (
        ("notify_attempts", "INT NOT NULL DEFAULT 0"),
        ("last_notify_attempt_at", "DATETIME NULL"),
        ("next_notify_attempt_at", "DATETIME NULL"),
    )
    for name, ddl in columns:
        if not _column_exists(cursor, name):
            cursor.execute(f"ALTER TABLE cm_bonus_redeem_requests ADD COLUMN {name} {ddl}")

    if not _index_exists(cursor, "idx_cm_bonus_redeem_retry"):
        cursor.execute("""
            ALTER TABLE cm_bonus_redeem_requests
            ADD KEY idx_cm_bonus_redeem_retry (status, next_notify_attempt_at)
            """)
