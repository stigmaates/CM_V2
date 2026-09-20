import importlib

migration = importlib.import_module("migrations.versions.0033_reusable_mission_templates")


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows


def test_migration_removes_all_unique_template_occupancy_indexes():
    cursor = Cursor(
        [
            {"INDEX_NAME": "PRIMARY", "NON_UNIQUE": 0, "SEQ_IN_INDEX": 1, "COLUMN_NAME": "id"},
            {
                "INDEX_NAME": "uq_club_template",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": "club_id",
            },
            {
                "INDEX_NAME": "uq_club_template",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 2,
                "COLUMN_NAME": "mission_template_id",
            },
            {
                "INDEX_NAME": "uq_active_club_template",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": "club_id",
            },
            {
                "INDEX_NAME": "uq_active_club_template",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 2,
                "COLUMN_NAME": "mission_template_id",
            },
            {
                "INDEX_NAME": "uq_active_club_template",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 3,
                "COLUMN_NAME": "is_enabled",
            },
        ]
    )

    migration.upgrade(cursor)

    statements = [" ".join(query.split()) for query, _params in cursor.executed]
    assert "ALTER TABLE club_missions ADD INDEX `idx_club_missions_club` (club_id)" in statements
    assert "ALTER TABLE club_missions DROP INDEX `uq_club_template`" in statements
    assert "ALTER TABLE club_missions DROP INDEX `uq_active_club_template`" in statements


def test_migration_keeps_primary_and_unrelated_unique_indexes():
    cursor = Cursor(
        [
            {"INDEX_NAME": "PRIMARY", "NON_UNIQUE": 0, "SEQ_IN_INDEX": 1, "COLUMN_NAME": "club_id"},
            {
                "INDEX_NAME": "PRIMARY",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 2,
                "COLUMN_NAME": "mission_template_id",
            },
            {"INDEX_NAME": "uq_mission_id", "NON_UNIQUE": 0, "SEQ_IN_INDEX": 1, "COLUMN_NAME": "id"},
            {
                "INDEX_NAME": "idx_club_missions_club",
                "NON_UNIQUE": 1,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": "club_id",
            },
        ]
    )

    migration.upgrade(cursor)

    assert len(cursor.executed) == 1
