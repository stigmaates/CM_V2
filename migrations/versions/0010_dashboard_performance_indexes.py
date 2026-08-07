"""Add indexes for dashboard and analytics queries."""

revision = "0010_dashboard_performance_indexes"


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def _columns_exist(cursor, table_name: str, columns: list[str]) -> bool:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME IN %s
        """,
        (table_name, tuple(columns)),
    )
    existing = {row["COLUMN_NAME"] for row in cursor.fetchall() or []}
    return set(columns).issubset(existing)


def _add_index(cursor, table_name: str, index_name: str, columns_sql: str) -> None:
    columns = [column.strip() for column in columns_sql.split(",")]
    if not _table_exists(cursor, table_name):
        return
    if not _columns_exist(cursor, table_name, columns):
        return
    if _index_exists(cursor, table_name, index_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD INDEX {index_name} ({columns_sql})")


def upgrade(cursor) -> None:
    _add_index(cursor, "guest_sessions", "idx_guest_sessions_club_date_guest", "club_id, date_start, guest_id")
    _add_index(cursor, "guest_sessions", "idx_guest_sessions_club_guest_date", "club_id, guest_id, date_start")
    _add_index(cursor, "guests", "idx_guests_club_dates", "club_id, date_insert, created_at")
    _add_index(cursor, "guests", "idx_guests_club_telegram", "club_id, telegram_id")
    _add_index(
        cursor,
        "guest_wheel_spins",
        "idx_guest_wheel_spins_club_date_guest",
        "club_id, created_at, guest_id",
    )
    _add_index(
        cursor,
        "guest_wheel_spins",
        "idx_guest_wheel_spins_club_guest_date",
        "club_id, guest_id, created_at",
    )
    _add_index(
        cursor,
        "guest_case_openings",
        "idx_guest_case_openings_club_date_guest",
        "club_id, created_at, guest_id",
    )
    _add_index(cursor, "guest_case_openings", "idx_guest_case_openings_club_case_date", "club_id, case_id, created_at")
    _add_index(cursor, "user_portrait", "idx_user_portrait_club_crm_telegram", "club_id, crm_type, has_telegram")
