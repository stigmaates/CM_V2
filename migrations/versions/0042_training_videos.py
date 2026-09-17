"""Global training video catalogue."""

revision = "0042_training_videos"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_videos (
            id BIGINT NOT NULL AUTO_INCREMENT,
            youtube_video_id VARCHAR(32) NOT NULL,
            youtube_url VARCHAR(500) NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            sort_order INT NOT NULL DEFAULT 0,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_training_videos_youtube_id (youtube_video_id),
            KEY idx_training_videos_visible_order (is_active, sort_order, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
