revision = "0045_game_contract_feature_toggle"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS game_contract_settings (
            club_id BIGINT NOT NULL,
            is_enabled TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        INSERT INTO game_contract_settings (club_id, is_enabled)
        SELECT existing.club_id, 1
        FROM (
            SELECT DISTINCT club_id FROM game_contract_reward_settings
            UNION
            SELECT DISTINCT club_id FROM guest_game_contracts
        ) AS existing
        ON DUPLICATE KEY UPDATE is_enabled=VALUES(is_enabled)
        """
    )
