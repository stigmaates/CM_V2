"""Add expiring Cyber Bonus grants."""

revision = "0008_expiring_cm_bonuses"


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
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


def _add_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def upgrade(cursor) -> None:
    _add_column(cursor, "cm_bonus_transactions", "expires_at", "DATETIME NULL AFTER status")
    _add_column(
        cursor, "cm_bonus_transactions", "expires_status", "VARCHAR(30) NOT NULL DEFAULT 'none' AFTER expires_at"
    )
    _add_column(cursor, "cm_bonus_transactions", "expired_at", "DATETIME NULL AFTER expires_status")
    _add_column(cursor, "cm_bonus_transactions", "expiration_transaction_id", "INT NULL AFTER expired_at")

    if not _index_exists(cursor, "cm_bonus_transactions", "idx_cm_bonus_expiration"):
        cursor.execute("""
            ALTER TABLE cm_bonus_transactions
            ADD KEY idx_cm_bonus_expiration (expires_status, expires_at)
            """)

    _add_column(cursor, "bonus_giveaways", "is_expiring", "TINYINT(1) NOT NULL DEFAULT 0 AFTER token_amount")
    _add_column(cursor, "bonus_giveaways", "expires_after_seconds", "INT NULL AFTER is_expiring")
    _add_column(cursor, "bonus_giveaways", "expires_at", "DATETIME NULL AFTER expires_after_seconds")
    _add_column(cursor, "bonus_giveaway_recipients", "expires_at", "DATETIME NULL AFTER token_amount")
