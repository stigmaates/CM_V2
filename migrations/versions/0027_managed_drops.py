"""One-shot, club-scoped prize assignments and their audit history."""

revision = "0027_managed_drops"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS managed_drops (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            kind VARCHAR(10) NOT NULL,
            target_id INT NOT NULL DEFAULT 0,
            prize_id INT NOT NULL,
            guest_name VARCHAR(255) NULL,
            guest_phone VARCHAR(80) NULL,
            target_name VARCHAR(255) NOT NULL,
            prize_name VARCHAR(255) NOT NULL,
            actor_user_id INT NOT NULL,
            actor_name VARCHAR(255) NULL,
            request_key VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL,
            finished_at DATETIME NULL,
            opening_id BIGINT NULL,
            cancelled_by INT NULL,
            reason VARCHAR(255) NULL,
            pending_slot TINYINT GENERATED ALWAYS AS
                (CASE WHEN status = 'pending' THEN 1 ELSE NULL END) STORED,
            UNIQUE KEY uq_managed_drop_pending (club_id, guest_id, kind, target_id, pending_slot),
            UNIQUE KEY uq_managed_drop_request (club_id, request_key),
            KEY idx_managed_drop_history (club_id, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
