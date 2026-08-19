"""Add configurable Cyber Bonus rewards for guest balance topups."""

revision = "0015_topup_bonus_rewards"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS club_topup_bonus_settings (
            club_id INT NOT NULL PRIMARY KEY,
            is_enabled TINYINT(1) NOT NULL DEFAULT 0,
            message_template TEXT NOT NULL,
            enabled_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS club_topup_bonus_rules (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            min_amount DECIMAL(12, 2) NOT NULL,
            bonus_amount INT NOT NULL,
            sort_order INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_topup_bonus_rule_threshold (club_id, min_amount),
            KEY idx_topup_bonus_rules_club (club_id, min_amount)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_topup_bonus_awards (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            topup_id BIGINT NOT NULL,
            guest_id BIGINT NOT NULL,
            rule_id INT NOT NULL,
            topup_amount DECIMAL(12, 2) NOT NULL,
            bonus_amount INT NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'awarded',
            delivery_status VARCHAR(30) NOT NULL DEFAULT 'pending',
            telegram_id BIGINT NULL,
            message_text TEXT NULL,
            error_text TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at DATETIME NULL,
            UNIQUE KEY uq_topup_bonus_award (club_id, topup_id),
            KEY idx_topup_bonus_awards_delivery (delivery_status, created_at),
            KEY idx_topup_bonus_awards_guest (club_id, guest_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
