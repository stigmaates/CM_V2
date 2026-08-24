"""Allow topup and welcome rewards to use either KB or wheel tokens."""

revision = "0020_configurable_reward_types"


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
        "club_topup_bonus_rules",
        "reward_type",
        "VARCHAR(20) NOT NULL DEFAULT 'cm_bonus' AFTER bonus_amount",
    )
    _add_column(
        cursor,
        "guest_topup_bonus_awards",
        "reward_type",
        "VARCHAR(20) NOT NULL DEFAULT 'cm_bonus' AFTER bonus_amount",
    )
    _add_column(
        cursor,
        "club_topup_bonus_settings",
        "welcome_reward_enabled",
        "TINYINT(1) NOT NULL DEFAULT 1 AFTER enabled_at",
    )
    _add_column(
        cursor,
        "club_topup_bonus_settings",
        "welcome_reward_type",
        "VARCHAR(20) NOT NULL DEFAULT 'tokens' AFTER welcome_reward_enabled",
    )
    _add_column(
        cursor,
        "club_topup_bonus_settings",
        "welcome_reward_amount",
        "INT NOT NULL DEFAULT 1 AFTER welcome_reward_type",
    )
