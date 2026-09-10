"""Durable completion facts, independent of mission visibility and rewards."""

from datetime import UTC, datetime


def record_mission_completion(cursor, club_id: int, guest_id: int, mission_id: int) -> None:
    # One completion per mission, matching the reward ledger's source identity.
    cursor.execute(
        """
        INSERT INTO guest_mission_completions (club_id, guest_id, mission_id, completed_at)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE completed_at = completed_at
        """,
        (club_id, guest_id, str(mission_id), datetime.now(UTC).replace(tzinfo=None)),
    )
