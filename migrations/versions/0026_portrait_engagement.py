"""Persist mission completions and extend the guest portrait with engagement."""

revision = "0026_portrait_engagement"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_mission_completions (
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            mission_id VARCHAR(120) NOT NULL,
            completed_at DATETIME NOT NULL,
            PRIMARY KEY (club_id, guest_id, mission_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    # Reward records survive mission deletion. Two reward currencies still mean
    # one completion; retain the earliest known timestamp on retries/backfills.
    cursor.execute("""
        INSERT INTO guest_mission_completions (club_id, guest_id, mission_id, completed_at)
        SELECT club_id, guest_id, source_id, MIN(created_at)
        FROM (
            SELECT club_id, guest_id, source_id, created_at
            FROM guest_wheel_token_transactions
            WHERE source_type = 'mission' AND amount > 0 AND source_id IS NOT NULL
            UNION ALL
            SELECT club_id, guest_id, source_id, created_at
            FROM cm_bonus_transactions
            WHERE source_type = 'mission' AND amount > 0 AND source_id IS NOT NULL
              AND status = 'done'
        ) rewards
        GROUP BY club_id, guest_id, source_id
        ON DUPLICATE KEY UPDATE completed_at = LEAST(completed_at, VALUES(completed_at))
        """)
    columns = {
        "avg_missions_per_month": "DECIMAL(12,2) NOT NULL DEFAULT 0",
        "case_openings_count": "INT NOT NULL DEFAULT 0",
        "last_case_opening_date": "DATETIME NULL",
        "case_openings_by_case": "JSON NULL",
    }
    for name, definition in columns.items():
        cursor.execute(
            """SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_portrait' AND COLUMN_NAME = %s""",
            (name,),
        )
        if not int((cursor.fetchone() or {}).get("cnt") or 0):
            cursor.execute(f"ALTER TABLE user_portrait ADD COLUMN {name} {definition}")
