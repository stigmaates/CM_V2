"""Track source links and the current club-side ticket status message."""

revision = "0032_support_ticket_message_tracking"


def _add_column(cursor, column_name: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'support_tickets'
          AND COLUMN_NAME = %s
        """,
        (column_name,),
    )
    row = cursor.fetchone() or {}
    if int(row.get("count") or 0) == 0:
        cursor.execute(f"ALTER TABLE support_tickets ADD COLUMN {definition}")


def upgrade(cursor):
    _add_column(cursor, "source_message_link", "source_message_link VARCHAR(512) NULL AFTER source_message_id")
    _add_column(cursor, "club_status_message_id", "club_status_message_id BIGINT NULL AFTER technical_message_id")
