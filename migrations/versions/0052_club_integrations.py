"""Identify a club's source system without changing existing Langame data."""

revision = "0052_club_integrations"


def upgrade(cursor):
    for name, definition in (
        ("integration_provider", "VARCHAR(16) NOT NULL DEFAULT 'langame'"),
        ("integration_ready", "TINYINT(1) NOT NULL DEFAULT 1"),
    ):
        cursor.execute(
            """SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clubs' AND COLUMN_NAME=%s""",
            (name,),
        )
        if not (cursor.fetchone() or {}).get("cnt"):
            cursor.execute(f"ALTER TABLE clubs ADD COLUMN {name} {definition}")
    cursor.execute("""CREATE TABLE IF NOT EXISTS club_integrations (
        club_id INT NOT NULL PRIMARY KEY,
        external_branch_id VARCHAR(100) NULL,
        settings JSON NULL,
        last_import_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
