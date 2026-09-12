"""Owner-managed working roster for the stage team report."""

revision = "0031_team_admin_settings"


def upgrade(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS team_admin_settings (
            club_id INT NOT NULL,
            admin_id BIGINT NOT NULL,
            is_working TINYINT NOT NULL DEFAULT 1,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id, admin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
    )
