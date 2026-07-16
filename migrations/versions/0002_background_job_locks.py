"""Add background job locks."""

revision = "0002_background_job_locks"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS background_job_locks (
            lock_key VARCHAR(160) PRIMARY KEY,
            job_type VARCHAR(80) NOT NULL,
            club_id INT NULL,
            owner_token VARCHAR(80) NOT NULL,
            acquired_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            metadata_json JSON NULL,
            KEY idx_background_job_locks_expires (expires_at),
            KEY idx_background_job_locks_club_job (club_id, job_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
