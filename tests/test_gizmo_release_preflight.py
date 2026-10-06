import pytest

from scripts.gizmo_release_preflight import candidate_revisions, database_report


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql):
        self.conn.sql.append(sql)
        assert sql == "START TRANSACTION READ ONLY" or sql.startswith("SELECT ")
        if "information_schema.TABLES" in sql:
            self.result = [{"TABLE_NAME": "schema_migrations"}]
        elif sql == "SELECT revision FROM schema_migrations":
            if self.conn.fail:
                raise RuntimeError("read failed")
            self.result = [{"revision": "0001"}, {"revision": "foreign_revision"}]
        elif "next_club_id" in sql:
            self.result = [{"clubs": 4, "next_club_id": 5}]
        elif "information_schema.COLUMNS" in sql:
            self.result = []

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class Connection:
    def __init__(self, fail=False):
        self.sql = []
        self.fail = fail
        self.rolled_back = False

    def cursor(self, *args):
        return Cursor(self)

    def rollback(self):
        self.rolled_back = True


def test_production_report_uses_read_only_transaction_and_lists_unknown_revisions():
    conn = Connection()
    report = database_report(conn, ["0001", "0002"])
    assert conn.sql[0] == "START TRANSACTION READ ONLY" and conn.rolled_back
    assert report["pending_migrations"] == ["0002"]
    assert report["unknown_applied_migrations"] == ["foreign_revision"]
    assert report["next_club_id"] == 5


def test_read_failure_still_rolls_back():
    conn = Connection(fail=True)
    with pytest.raises(RuntimeError):
        database_report(conn, [])
    assert conn.rolled_back


def test_migration_inspection_never_executes_module(tmp_path):
    directory = tmp_path / "migrations/versions"
    directory.mkdir(parents=True)
    (directory / "0001_test.py").write_text("revision='0001'\nraise RuntimeError('must not run')\n")
    assert candidate_revisions(tmp_path) == ["0001"]
