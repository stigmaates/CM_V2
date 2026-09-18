"""Steam game preferences for CRM and contract events for Guest Pulse."""

revision = "0044_game_preferences_and_contract_engagement"


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (table_name, column_name),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
        """,
        (table_name, index_name),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def upgrade(cursor) -> None:
    for name, ddl in {
        "cs2_hours_total": "DECIMAL(12,1) NULL",
        "cs2_hours_2weeks": "DECIMAL(12,1) NULL",
        "dota2_hours_total": "DECIMAL(12,1) NULL",
        "dota2_hours_2weeks": "DECIMAL(12,1) NULL",
        "game_stats_updated_at": "DATETIME NULL",
        "game_stats_attempted_at": "DATETIME NULL",
    }.items():
        _ensure_column(cursor, "guest_steam_accounts", name, ddl)

    for name, ddl in {
        "favorite_game": "VARCHAR(16) NULL",
        "favorite_game_hours": "DECIMAL(12,1) NULL",
        "recent_game_14d": "VARCHAR(16) NULL",
        "recent_game_14d_hours": "DECIMAL(12,1) NULL",
        "steam_game_stats_updated_at": "DATETIME NULL",
    }.items():
        _ensure_column(cursor, "user_portrait", name, ddl)

    for index_name, columns in {
        "idx_user_portrait_favorite_game": "club_id, favorite_game",
        "idx_user_portrait_recent_game": "club_id, recent_game_14d",
    }.items():
        if not _index_exists(cursor, "user_portrait", index_name):
            cursor.execute(f"ALTER TABLE user_portrait ADD KEY {index_name} ({columns})")

    cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
    existing = {row["TRIGGER_NAME"] for row in cursor.fetchall()}
    for operation in ("INSERT", "UPDATE", "DELETE"):
        name = f"guest_pulse_contract_{operation.lower()}"
        if name in existing:
            continue
        ref = "OLD" if operation == "DELETE" else "NEW"
        cursor.execute(f"""CREATE TRIGGER {name} AFTER {operation} ON guest_game_contracts
            FOR EACH ROW INSERT INTO guest_pulse_dirty (club_id, generation)
            SELECT {ref}.club_id, 1 WHERE {ref}.club_id IS NOT NULL
            ON DUPLICATE KEY UPDATE generation=generation+1""")
