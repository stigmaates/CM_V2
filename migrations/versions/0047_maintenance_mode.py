"""Add global and per-club maintenance mode settings."""

revision = "0047_maintenance_mode"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS module_maintenance_settings (
            club_id BIGINT NOT NULL,
            is_enabled TINYINT(1) NOT NULL DEFAULT 0,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        INSERT INTO module_maintenance_settings (club_id, is_enabled)
        VALUES (0, 0)
        ON DUPLICATE KEY UPDATE club_id=VALUES(club_id)
        """
    )
