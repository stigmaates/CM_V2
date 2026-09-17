"""Linked Steam accounts for guest game profiles."""

revision = "0036_guest_steam_accounts"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_steam_accounts (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            steam_id BIGINT UNSIGNED NOT NULL,
            persona_name VARCHAR(255) NULL,
            profile_url TEXT NULL,
            avatar_url TEXT NULL,
            linked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_steam_account (club_id, guest_id),
            UNIQUE KEY uq_club_steam_account (club_id, steam_id),
            KEY idx_guest_steam_id (steam_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
