"""Weekly CS2 and Dota 2 contracts with idempotent match progress."""

revision = "0038_game_contracts"


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (table_name, column_name),
    )
    if int((cursor.fetchone() or {}).get("count") or 0) == 0:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def upgrade(cursor) -> None:
    _ensure_column(cursor, "guest_cs2_matches", "headshots", "INT NOT NULL DEFAULT 0 AFTER assists")
    _ensure_column(cursor, "guest_cs2_matches", "mvp", "INT NOT NULL DEFAULT 0 AFTER headshots")
    _ensure_column(cursor, "guest_cs2_matches", "weapon_kills_json", "LONGTEXT NULL AFTER mvp")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_contract_templates (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            game VARCHAR(16) NOT NULL,
            title VARCHAR(255) NOT NULL,
            description_template TEXT NOT NULL,
            metric_type VARCHAR(64) NOT NULL,
            target_value DECIMAL(14,2) NOT NULL,
            period_type VARCHAR(16) NOT NULL DEFAULT 'week',
            difficulty VARCHAR(16) NOT NULL,
            reward_tokens INT NOT NULL DEFAULT 0,
            reward_bonus INT NOT NULL DEFAULT 0,
            weight INT NOT NULL DEFAULT 100,
            conditions_json LONGTEXT NULL,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_contract_templates_pool (club_id, game, is_active, difficulty),
            KEY idx_contract_templates_metric (club_id, game, metric_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_game_contract_sets (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            steam_id VARCHAR(32) NOT NULL,
            game VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            started_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            finalized_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_contract_sets_guest (club_id, guest_id, game, started_at),
            KEY idx_contract_sets_active (status, expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_game_contracts (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            set_id BIGINT NOT NULL,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            steam_id VARCHAR(32) NOT NULL,
            game VARCHAR(16) NOT NULL,
            template_id BIGINT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            metric_type VARCHAR(64) NOT NULL,
            target_value DECIMAL(14,2) NOT NULL,
            current_value DECIMAL(14,2) NOT NULL DEFAULT 0,
            period_type VARCHAR(16) NOT NULL,
            difficulty VARCHAR(16) NOT NULL,
            reward_tokens INT NOT NULL DEFAULT 0,
            reward_bonus INT NOT NULL DEFAULT 0,
            conditions_json LONGTEXT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            started_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            completed_at DATETIME NULL,
            reward_claimed_at DATETIME NULL,
            last_checked_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_contract_set_template (set_id, template_id),
            KEY idx_guest_contracts_active (club_id, guest_id, game, status, expires_at),
            KEY idx_guest_contracts_template (template_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_match_stats (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            steam_id VARCHAR(32) NOT NULL,
            game VARCHAR(16) NOT NULL,
            match_id VARCHAR(80) NOT NULL,
            match_started_at DATETIME NOT NULL,
            map_name VARCHAR(128) NULL,
            hero_id INT NULL,
            hero_name VARCHAR(128) NULL,
            kills INT NOT NULL DEFAULT 0,
            deaths INT NOT NULL DEFAULT 0,
            assists INT NOT NULL DEFAULT 0,
            headshots INT NOT NULL DEFAULT 0,
            damage INT NOT NULL DEFAULT 0,
            last_hits INT NOT NULL DEFAULT 0,
            gpm INT NOT NULL DEFAULT 0,
            xpm INT NOT NULL DEFAULT 0,
            mvp INT NOT NULL DEFAULT 0,
            won TINYINT(1) NULL,
            raw_stats_json LONGTEXT NULL,
            source VARCHAR(32) NOT NULL,
            parser_version VARCHAR(32) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_game_match_guest (club_id, guest_id, game, match_id),
            KEY idx_game_match_contract_window (club_id, guest_id, game, match_started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_contract_match_contributions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            contract_id BIGINT NOT NULL,
            guest_id INT NOT NULL,
            game VARCHAR(16) NOT NULL,
            match_id VARCHAR(80) NOT NULL,
            contribution_value DECIMAL(14,2) NOT NULL DEFAULT 0,
            details_json LONGTEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_contract_match_contribution (contract_id, match_id),
            KEY idx_contract_contributions_contract (contract_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_contract_progress_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            contract_id BIGINT NOT NULL,
            guest_id INT NOT NULL,
            game VARCHAR(16) NOT NULL,
            match_id VARCHAR(80) NULL,
            old_value DECIMAL(14,2) NOT NULL DEFAULT 0,
            added_value DECIMAL(14,2) NOT NULL DEFAULT 0,
            new_value DECIMAL(14,2) NOT NULL DEFAULT 0,
            event_type VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_contract_progress_log (contract_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_game_sync_state (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            game VARCHAR(16) NOT NULL,
            last_attempt_at DATETIME NULL,
            last_synced_at DATETIME NULL,
            last_error VARCHAR(500) NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_game_sync_state (club_id, guest_id, game),
            KEY idx_guest_game_sync_errors (game, last_attempt_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
