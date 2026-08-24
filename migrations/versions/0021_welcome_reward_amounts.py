"""Allow a welcome reward to include both KB and wheel tokens."""

revision = "0021_welcome_reward_amounts"


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
    return int((cursor.fetchone() or {}).get("cnt") or 0) > 0


def _add_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def upgrade(cursor) -> None:
    _add_column(
        cursor,
        "club_topup_bonus_settings",
        "welcome_cm_bonus_amount",
        "INT NOT NULL DEFAULT 0 AFTER welcome_reward_amount",
    )
    _add_column(
        cursor,
        "club_topup_bonus_settings",
        "welcome_token_amount",
        "INT NOT NULL DEFAULT 1 AFTER welcome_cm_bonus_amount",
    )
    cursor.execute(
        """
        UPDATE club_topup_bonus_settings
        SET welcome_cm_bonus_amount = CASE
                WHEN welcome_reward_type = 'cm_bonus' THEN welcome_reward_amount
                ELSE 0
            END,
            welcome_token_amount = CASE
                WHEN welcome_reward_type = 'tokens' THEN welcome_reward_amount
                ELSE 0
            END
        """
    )
