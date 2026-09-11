"""Guest Pulse current scores, immutable daily history, lifecycle events and dirty queue."""

revision = "0028_guest_pulse"


def upgrade(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_pulse_current (
        club_id INT NOT NULL, guest_id BIGINT NOT NULL,
        health_score DECIMAL(6,2) NULL, value_score DECIMAL(6,2) NULL, engagement_score DECIMAL(6,2) NULL,
        lifecycle_status VARCHAR(32) NOT NULL, audience_type VARCHAR(32) NOT NULL,
        detail_json JSON NOT NULL, calculated_at DATETIME NOT NULL,
        PRIMARY KEY (club_id, guest_id), KEY idx_pulse_audience (club_id, audience_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_score_history (
        club_id INT NOT NULL, guest_id BIGINT NOT NULL, snapshot_date DATE NOT NULL,
        health_score DECIMAL(6,2) NULL, value_score DECIMAL(6,2) NULL, engagement_score DECIMAL(6,2) NULL,
        lifecycle_status VARCHAR(32) NOT NULL, detail_json JSON NOT NULL,
        reconstructed TINYINT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL,
        PRIMARY KEY (club_id, guest_id, snapshot_date), KEY idx_score_history_day (club_id, snapshot_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_lifecycle_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY, club_id INT NOT NULL, guest_id BIGINT NOT NULL,
        from_status VARCHAR(32) NULL, to_status VARCHAR(32) NOT NULL, changed_at DATETIME NOT NULL,
        health_before DECIMAL(6,2) NULL, health_after DECIMAL(6,2) NULL, reason_code VARCHAR(64) NOT NULL,
        reconstructed TINYINT NOT NULL DEFAULT 0,
        UNIQUE KEY uq_lifecycle_event (club_id, guest_id, changed_at, to_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_pulse_clubs (
        club_id INT PRIMARY KEY, calculated_at DATETIME NULL, snapshot_date DATE NULL,
        backfilled_at DATETIME NULL, guest_count INT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_pulse_dirty (
        club_id INT PRIMARY KEY, generation BIGINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # Projections for existing CRM consumers; authoritative explanation/history are separate.
    for name, definition in {
        "health_score": "DECIMAL(6,2) NULL",
        "value_score": "DECIMAL(6,2) NULL",
        "engagement_score": "DECIMAL(6,2) NULL",
        "lifecycle_status": "VARCHAR(32) NULL",
        "health_delta_14d": "DECIMAL(6,2) NULL",
        "pulse_updated_at": "DATETIME NULL",
    }.items():
        cursor.execute(
            """SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_portrait' AND COLUMN_NAME=%s""",
            (name,),
        )
        if not (cursor.fetchone() or {}).get("cnt"):
            cursor.execute(f"ALTER TABLE user_portrait ADD COLUMN {name} {definition}")
    # Trigger only records invalidation, in the source transaction. Scores are never
    # calculated during reward issuance. This also covers the separate bot processes.
    tables = (
        "guest_sessions",
        "guest_balance_topups",
        "guests",
        "guest_mission_completions",
        "guest_wheel_spins",
        "guest_case_openings",
        "cm_bonus_transactions",
        "guest_prize_claims",
        "cm_bonus_redeem_requests",
        "guest_wheel_token_transactions",
    )
    cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
    existing = {r["TRIGGER_NAME"] for r in cursor.fetchall()}
    for index, table in enumerate(tables):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            name = f"guest_pulse_{index}_{operation.lower()}"
            if name in existing:
                continue
            ref = "OLD" if operation == "DELETE" else "NEW"
            cursor.execute(f"""CREATE TRIGGER {name} AFTER {operation} ON {table}
                FOR EACH ROW INSERT INTO guest_pulse_dirty (club_id, generation)
                SELECT {ref}.club_id, 1 WHERE {ref}.club_id IS NOT NULL
                ON DUPLICATE KEY UPDATE generation=generation+1""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS guest_pulse_selections (
        id CHAR(32) PRIMARY KEY, club_id INT NOT NULL, user_id BIGINT NOT NULL,
        selection_json JSON NOT NULL, created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL,
        mailing_id BIGINT NULL, KEY idx_pulse_selection_expiry (expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
