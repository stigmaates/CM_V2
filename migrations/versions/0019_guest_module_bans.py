"""Add club-scoped guest access bans for the Cyber Bonus module."""

revision = "0019_guest_module_bans"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_module_bans (
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            is_banned TINYINT(1) NOT NULL DEFAULT 1,
            reason VARCHAR(255) NULL,
            banned_by_user_id INT NULL,
            banned_at DATETIME NULL,
            unbanned_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id, guest_id),
            KEY idx_guest_module_bans_active (club_id, is_banned)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
