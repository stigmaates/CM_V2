import importlib

case_badge_colors = importlib.import_module("migrations.versions.0023_case_badge_colors")


class _Cursor:
    def __init__(self, *, column_exists):
        self.column_exists = column_exists
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return {"cnt": 1 if self.column_exists else 0}


def test_case_badge_color_migration_adds_missing_column():
    cursor = _Cursor(column_exists=False)

    case_badge_colors.upgrade(cursor)

    queries = "\n".join(query for query, _params in cursor.executed)
    assert "ALTER TABLE club_cases" in queries
    assert "badge_color VARCHAR(7)" in queries
    assert "DEFAULT '#8F5BFF'" in queries


def test_case_badge_color_migration_is_idempotent():
    cursor = _Cursor(column_exists=True)

    case_badge_colors.upgrade(cursor)

    queries = "\n".join(query for query, _params in cursor.executed)
    assert "ALTER TABLE club_cases" not in queries
