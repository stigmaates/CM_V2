"""Add portrait confidence fields and smart inactivity settings."""

revision = "0051_smart_inactive_auto_mailing"


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (table_name, column_name),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def upgrade(cursor) -> None:
    portrait_columns = (
        ("profile_confidence_score", "DECIMAL(6,2) NULL AFTER engagement_score"),
        ("usual_interval_days", "DECIMAL(8,2) NULL AFTER profile_confidence_score"),
    )
    for name, definition in portrait_columns:
        if not _column_exists(cursor, "user_portrait", name):
            cursor.execute(f"ALTER TABLE user_portrait ADD COLUMN {name} {definition}")

    settings_columns = (
        ("smart_inactive_enabled", "TINYINT(1) NOT NULL DEFAULT 0 AFTER days_inactive"),
        ("smart_inactive_days", "INT NOT NULL DEFAULT 14 AFTER smart_inactive_enabled"),
        ("smart_interval_multiplier", "DECIMAL(5,2) NOT NULL DEFAULT 3.00 AFTER smart_inactive_days"),
    )
    added_smart_days = False
    for name, definition in settings_columns:
        if not _column_exists(cursor, "auto_mailing_settings", name):
            cursor.execute(f"ALTER TABLE auto_mailing_settings ADD COLUMN {name} {definition}")
            added_smart_days = added_smart_days or name == "smart_inactive_days"
    if added_smart_days:
        cursor.execute(
            """UPDATE auto_mailing_settings
            SET smart_inactive_days=days_inactive
            WHERE code='inactive_14_bonus'"""
        )

    cursor.execute(
        """INSERT INTO guest_pulse_dirty (club_id,generation)
        SELECT club_id,1 FROM clubs
        ON DUPLICATE KEY UPDATE generation=generation+1"""
    )
