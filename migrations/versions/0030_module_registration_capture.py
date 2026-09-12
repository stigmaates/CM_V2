"""Persist the first successful Cyber Bonus Telegram registration."""

revision = "0030_module_registration_capture"


def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS module_registrations (
            club_id INT NOT NULL,
            guest_id BIGINT NOT NULL,
            registered_at DATETIME NULL,
            source VARCHAR(40) NOT NULL,
            is_estimated TINYINT NOT NULL DEFAULT 0,
            observed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id, guest_id),
            KEY idx_module_registered (club_id, registered_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
