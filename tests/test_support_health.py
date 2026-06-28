from app.services import support_health


class FakeCursor:
    def __init__(self, applied=None):
        self.applied = applied or []
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        self.last_query = query
        if "schema_migrations" in query and self.applied is None:
            raise RuntimeError("missing table")

    def fetchone(self):
        if "COUNT" in self.last_query:
            return {"cnt": 3}
        return {"ok": 1}

    def fetchall(self):
        return [{"revision": revision} for revision in (self.applied or [])]


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_system_health_ok_when_migrations_are_applied(monkeypatch):
    monkeypatch.setattr(support_health, "get_expected_migration_revisions", lambda: ["0001"])
    conn = FakeConnection(FakeCursor(applied=["0001"]))
    monkeypatch.setattr(support_health, "get_db_connection", lambda: conn)

    health = support_health.get_admin_system_health()

    assert health["ok"] is True
    assert "release" in health
    assert health["database"]["ok"] is True
    assert health["migrations"]["pending"] == []
    assert health["counts"]["clubs"] == 3
    assert conn.closed is True


def test_system_health_reports_pending_migrations(monkeypatch):
    monkeypatch.setattr(support_health, "get_expected_migration_revisions", lambda: ["0001"])
    conn = FakeConnection(FakeCursor(applied=[]))
    monkeypatch.setattr(support_health, "get_db_connection", lambda: conn)

    health = support_health.get_admin_system_health()

    assert health["ok"] is False
    assert health["database"]["ok"] is True
    assert health["migrations"]["pending"] == ["0001"]
