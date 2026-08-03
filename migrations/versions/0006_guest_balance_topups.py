"""Add Langame guest balance topups."""

revision = "0006_guest_balance_topups"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_balance_topups (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            topup_id BIGINT NOT NULL,
            guest_id BIGINT NOT NULL,
            guest_name VARCHAR(255) NULL,
            phone VARCHAR(32) NULL,
            amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
            topup_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            UNIQUE KEY uq_guest_balance_topup (club_id, topup_id),
            KEY idx_guest_balance_topups_guest (club_id, guest_id, topup_at),
            KEY idx_guest_balance_topups_phone (club_id, phone, topup_at),
            KEY idx_guest_balance_topups_topup_at (club_id, topup_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
