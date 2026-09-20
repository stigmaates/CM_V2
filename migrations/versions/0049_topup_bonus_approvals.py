"""Require an owner approval before granting a top-up reward."""

revision = "0049_topup_bonus_approvals"


def _column_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_topup_bonus_awards'
          AND COLUMN_NAME = %s
        """,
        (name,),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def _index_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_topup_bonus_awards'
          AND INDEX_NAME = %s
        """,
        (name,),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def upgrade(cursor) -> None:
    columns = (
        ("rule_min_amount", "DECIMAL(12, 2) NULL AFTER rule_id"),
        ("reviewed_by", "INT NULL AFTER error_text"),
        ("reviewed_at", "DATETIME NULL AFTER reviewed_by"),
        ("rejection_reason", "VARCHAR(500) NULL AFTER reviewed_at"),
    )
    for name, definition in columns:
        if not _column_exists(cursor, name):
            cursor.execute(f"ALTER TABLE guest_topup_bonus_awards ADD COLUMN {name} {definition}")

    cursor.execute(
        """
        UPDATE guest_topup_bonus_awards a
        JOIN club_topup_bonus_rules r ON r.id = a.rule_id AND r.club_id = a.club_id
        SET a.rule_min_amount = r.min_amount
        WHERE a.rule_min_amount IS NULL
        """
    )

    if not _index_exists(cursor, "idx_topup_bonus_awards_review"):
        cursor.execute(
            """
            ALTER TABLE guest_topup_bonus_awards
            ADD KEY idx_topup_bonus_awards_review (club_id, status, created_at)
            """
        )
