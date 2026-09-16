"""CS2 match-history credentials and cached match summaries."""

revision = "0037_guest_cs2_matches"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_cs2_match_access (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            auth_code_encrypted TEXT NOT NULL,
            last_share_code VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_cs2_match_access (club_id, guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_cs2_matches (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            share_code VARCHAR(64) NOT NULL,
            match_id VARCHAR(32) NULL,
            played_at BIGINT NULL,
            map_name VARCHAR(120) NULL,
            mode_label VARCHAR(120) NULL,
            result_label VARCHAR(32) NULL,
            won TINYINT(1) NULL,
            team_score INT NULL,
            opponent_score INT NULL,
            duration_seconds INT NULL,
            kills INT NULL,
            deaths INT NULL,
            assists INT NULL,
            headshots INT NOT NULL DEFAULT 0,
            mvp INT NOT NULL DEFAULT 0,
            weapon_kills_json LONGTEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_cs2_match_code (club_id, guest_id, share_code),
            KEY idx_guest_cs2_matches_recent (club_id, guest_id, played_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
