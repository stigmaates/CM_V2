"""Store topup reward timestamps in Moscow local time."""

revision = "0016_topup_bonus_moscow_timestamps"


def upgrade(cursor) -> None:
    cursor.execute("""
        UPDATE club_topup_bonus_settings
        SET enabled_at = DATE_ADD(enabled_at, INTERVAL 3 HOUR)
        WHERE enabled_at IS NOT NULL
        """)
    cursor.execute("""
        UPDATE guest_topup_bonus_awards
        SET created_at = DATE_ADD(created_at, INTERVAL 3 HOUR),
            sent_at = CASE
                WHEN sent_at IS NULL THEN NULL
                ELSE DATE_ADD(sent_at, INTERVAL 3 HOUR)
            END
        """)
    cursor.execute("""
        UPDATE cm_bonus_transactions
        SET created_at = DATE_ADD(created_at, INTERVAL 3 HOUR)
        WHERE source_type = 'topup_reward'
        """)
