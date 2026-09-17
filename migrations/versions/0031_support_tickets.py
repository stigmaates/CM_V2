"""Store club support tickets and their status history."""

revision = "0031_support_tickets"


def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            club_id INT NOT NULL,
            source_chat_id VARCHAR(80) NOT NULL,
            source_chat_title VARCHAR(255) NULL,
            source_message_id BIGINT NULL,
            author_telegram_id BIGINT NULL,
            author_username VARCHAR(255) NULL,
            author_name VARCHAR(255) NULL,
            message_text TEXT NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'waiting',
            assigned_to_telegram_id BIGINT NULL,
            assigned_to_username VARCHAR(255) NULL,
            assigned_to_name VARCHAR(255) NULL,
            technical_chat_id VARCHAR(80) NULL,
            technical_message_id BIGINT NULL,
            delivery_error TEXT NULL,
            created_at DATETIME NOT NULL,
            taken_at DATETIME NULL,
            paused_at DATETIME NULL,
            completed_at DATETIME NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            KEY idx_support_ticket_club_created (club_id, created_at),
            KEY idx_support_ticket_status_updated (status, updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_ticket_events (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            ticket_id BIGINT UNSIGNED NOT NULL,
            action VARCHAR(24) NOT NULL,
            old_status VARCHAR(24) NULL,
            new_status VARCHAR(24) NOT NULL,
            actor_telegram_id BIGINT NULL,
            actor_username VARCHAR(255) NULL,
            actor_name VARCHAR(255) NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            KEY idx_support_ticket_event_ticket (ticket_id, created_at),
            CONSTRAINT fk_support_ticket_event_ticket
                FOREIGN KEY (ticket_id) REFERENCES support_tickets (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
