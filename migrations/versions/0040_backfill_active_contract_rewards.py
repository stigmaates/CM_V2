"""Backfill configured rewards into unrewarded active contract pools."""

revision = "0040_backfill_active_contract_rewards"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        UPDATE guest_game_contracts c
        JOIN game_contract_reward_settings r
          ON r.club_id=c.club_id AND r.difficulty=c.difficulty
        SET c.reward_tokens=r.reward_tokens,
            c.reward_bonus=r.reward_bonus,
            c.updated_at=CURRENT_TIMESTAMP
        WHERE c.status IN ('offered', 'active')
          AND c.reward_claimed_at IS NULL
          AND c.reward_tokens=0
          AND c.reward_bonus=0
        """
    )
