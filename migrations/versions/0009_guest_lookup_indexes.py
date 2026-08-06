"""Add guest lookup indexes for multi-club sync and login."""

revision = "0009_guest_lookup_indexes"


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


def upgrade(cursor) -> None:
    if not _table_exists(cursor, "guests"):
        return

    if not _index_exists(cursor, "guests", "idx_guests_club_guest"):
        cursor.execute("""
            ALTER TABLE guests
            ADD INDEX idx_guests_club_guest (club_id, guest_id)
        """)

    if not _index_exists(cursor, "guests", "idx_guests_club_phone"):
        cursor.execute("""
            ALTER TABLE guests
            ADD INDEX idx_guests_club_phone (club_id, phone)
        """)
