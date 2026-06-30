import importlib

import scripts.migrate as migrate_script


def test_product_readiness_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0001_product_readiness_schema")

    assert migration.revision == "0001_product_readiness_schema"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "background_job_runs" in value
        for value in migration.upgrade.__code__.co_consts
    )


def test_background_job_locks_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0002_background_job_locks")

    assert migration.revision == "0002_background_job_locks"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "background_job_locks" in value
        for value in migration.upgrade.__code__.co_consts
    )


class _Cursor:
    def __init__(self):
        self.applied = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if query.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return
        if query == "SELECT revision FROM schema_migrations":
            return
        if query.startswith("INSERT INTO schema_migrations"):
            self.applied = True

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("dry-run should not rollback")

    def close(self):
        self.closed = True


def test_migrate_dry_run_lists_pending_without_applying(monkeypatch, capsys):
    conn = _Connection()

    monkeypatch.setattr(migrate_script, "get_db_connection", lambda: conn)

    assert migrate_script.migrate(dry_run=True) == 0

    output = capsys.readouterr().out
    assert "Pending migrations:" in output
    assert "0001_product_readiness_schema" in output
    assert conn.cursor_obj.applied is False
    assert conn.committed is False
    assert conn.closed is True
