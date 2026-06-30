"""Add operational alert notification dedupe state."""

revision = "0003_operational_alert_notifications"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS operational_alert_notifications (
            alert_key VARCHAR(191) PRIMARY KEY,
            severity VARCHAR(30) NOT NULL,
            code VARCHAR(80) NOT NULL,
            club_id INT NULL,
            message TEXT NULL,
            metadata_json JSON NULL,
            last_sent_at DATETIME NOT NULL,
            send_count INT NOT NULL DEFAULT 1,
            KEY idx_operational_alert_notifications_last_sent (last_sent_at),
            KEY idx_operational_alert_notifications_club_code (club_id, code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
