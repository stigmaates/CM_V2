"""Persistent, administrator-reviewed Telegram account linking."""

revision = "0024_telegram_link_requests"


def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_telegram_link_requests (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            telegram_id BIGINT NOT NULL,
            telegram_phone VARCHAR(32) NOT NULL,
            lg_phone VARCHAR(32) NOT NULL,
            admin_chat_id VARCHAR(80) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            reviewed_by BIGINT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at DATETIME NULL,
            KEY idx_link_request_sender (club_id, telegram_id, created_at),
            KEY idx_link_request_guest (club_id, guest_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
