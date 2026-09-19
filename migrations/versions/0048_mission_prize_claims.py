"""Allow physical mission rewards to use the shared prize claim workflow."""

revision = "0048_mission_prize_claims"


def _column(cursor, name: str):
    cursor.execute(
        """
        SELECT IS_NULLABLE AS is_nullable
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_prize_claims'
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (name,),
    )
    return cursor.fetchone()


def _index_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_prize_claims'
          AND INDEX_NAME = %s
        """,
        (name,),
    )
    return int((cursor.fetchone() or {}).get("count") or 0) > 0


def upgrade(cursor) -> None:
    if not _column(cursor, "source_type"):
        cursor.execute(
            """
            ALTER TABLE guest_prize_claims
            ADD COLUMN source_type VARCHAR(40) NULL AFTER spin_id
            """
        )
    if not _column(cursor, "source_id"):
        cursor.execute(
            """
            ALTER TABLE guest_prize_claims
            ADD COLUMN source_id VARCHAR(120) NULL AFTER source_type
            """
        )

    cursor.execute(
        """
        UPDATE guest_prize_claims
        SET source_type = CASE WHEN spin_id < 0 THEN 'case_opening' ELSE 'wheel_spin' END,
            source_id = CAST(ABS(spin_id) AS CHAR)
        WHERE source_type IS NULL OR source_id IS NULL
        """
    )

    spin_column = _column(cursor, "spin_id") or {}
    if str(spin_column.get("is_nullable") or "").upper() != "YES":
        cursor.execute("ALTER TABLE guest_prize_claims MODIFY COLUMN spin_id INT NULL")

    if not _index_exists(cursor, "uq_prize_claim_source"):
        cursor.execute(
            """
            ALTER TABLE guest_prize_claims
            ADD UNIQUE KEY uq_prize_claim_source (
                club_id,
                guest_id,
                source_type,
                source_id
            )
            """
        )

