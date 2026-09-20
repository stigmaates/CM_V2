"""Track Telegram notifications and Telegram reviews for top-up rewards."""

revision = "0050_topup_bonus_admin_notifications"


def _column_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_topup_bonus_awards'
          AND COLUMN_NAME = %s
        """,
        (name,),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def upgrade(cursor) -> None:
    columns = (
        ("admin_chat_id", "VARCHAR(80) NULL AFTER rejection_reason"),
        ("admin_message_id", "BIGINT NULL AFTER admin_chat_id"),
        (
            "admin_notification_status",
            "VARCHAR(30) NOT NULL DEFAULT 'pending' AFTER admin_message_id",
        ),
        ("admin_notification_error", "TEXT NULL AFTER admin_notification_status"),
        ("admin_notified_at", "DATETIME NULL AFTER admin_notification_error"),
        ("reviewed_by_telegram_id", "BIGINT NULL AFTER admin_notified_at"),
        ("reviewed_by_username", "VARCHAR(255) NULL AFTER reviewed_by_telegram_id"),
    )
    for name, definition in columns:
        if not _column_exists(cursor, name):
            cursor.execute(f"ALTER TABLE guest_topup_bonus_awards ADD COLUMN {name} {definition}")

