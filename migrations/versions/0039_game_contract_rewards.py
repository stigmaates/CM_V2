"""Club rewards by generated game-contract difficulty."""

revision = "0039_game_contract_rewards"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS game_contract_reward_settings (
            club_id INT NOT NULL,
            difficulty VARCHAR(16) NOT NULL,
            reward_tokens INT NOT NULL DEFAULT 0,
            reward_bonus INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id, difficulty)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
