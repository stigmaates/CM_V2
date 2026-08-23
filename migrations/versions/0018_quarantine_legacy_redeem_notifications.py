"""Quarantine legacy redeem notifications from the retry queue."""

revision = "0018_quarantine_legacy_redeem_notifications"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        UPDATE cm_bonus_redeem_requests
        SET status = 'notify_failed_legacy',
            next_notify_attempt_at = NULL
        WHERE telegram_message_id IS NULL
          AND status IN ('created', 'notify_failed', 'notify_retrying')
        """
    )
