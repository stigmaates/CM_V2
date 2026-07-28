"""Add giveaway wheel tokens and personal mailing messages."""

revision = "0005_giveaway_tokens_and_personal_messages"


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


def _add_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def upgrade(cursor) -> None:
    _add_column(cursor, "mailing_recipients", "message_text", "TEXT NULL AFTER telegram_id")
    _add_column(cursor, "bonus_giveaways", "token_amount", "INT NOT NULL DEFAULT 0 AFTER bonus_amount")
    _add_column(cursor, "bonus_giveaways", "token_awarded_count", "INT NOT NULL DEFAULT 0 AFTER awarded_count")
    _add_column(cursor, "bonus_giveaway_recipients", "token_amount", "INT NOT NULL DEFAULT 0 AFTER bonus_amount")
    _add_column(
        cursor,
        "bonus_giveaway_recipients",
        "token_transaction_status",
        "VARCHAR(40) NOT NULL DEFAULT 'pending' AFTER transaction_status",
    )
    _add_column(cursor, "bonus_giveaway_recipients", "token_transaction_id", "INT NULL AFTER transaction_id")
    _add_column(cursor, "bonus_giveaway_recipients", "token_error_text", "TEXT NULL AFTER error_text")
