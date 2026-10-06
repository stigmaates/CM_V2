"""Keep historical PC identities without returning them to the active inventory."""

revision = "0053_archived_club_pcs"


def upgrade(cursor):
    cursor.execute("""SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='club_pc_names' AND COLUMN_NAME='is_archived'""")
    if not (cursor.fetchone() or {}).get("cnt"):
        cursor.execute("ALTER TABLE club_pc_names ADD COLUMN is_archived TINYINT(1) NOT NULL DEFAULT 0")
