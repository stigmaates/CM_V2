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


def test_admin_readiness_success_when_core_checks_are_green(monkeypatch, tmp_path):
    monkeypatch.setattr(support_health, "CLUBMODULE_UPLOAD_ROOT", str(tmp_path))
    monkeypatch.setattr(support_health, "TECH_ALERT_BOT_TOKEN", "token")
    monkeypatch.setattr(support_health, "TECH_ALERT_CHAT_ID", "chat")

    readiness = support_health.build_admin_readiness(
        system_health={
            "database": {"ok": True},
            "migrations": {"pending": [], "latest": "0003"},
            "release": {"version": "stage", "commit": "abcdef1"},
        },
        alert_summary={"error": 0, "warning": 0},
        sync_summary={"error": 0, "stale": 0},
        recent_job_runs=[{"status": "success"}],
        backup_status={"status": "success", "message": "Последний backup: 2 ч назад"},
    )

    assert readiness["overall_status"] == "success"
    statuses = {item["key"]: item["status"] for item in readiness["items"]}
    assert statuses["upload_storage"] == "success"
    assert statuses["backups"] == "success"


def test_admin_readiness_reports_errors_and_warnings(monkeypatch, tmp_path):
    missing_upload_dir = tmp_path / "missing"
    monkeypatch.setattr(support_health, "CLUBMODULE_UPLOAD_ROOT", str(missing_upload_dir))
    monkeypatch.setattr(support_health, "TECH_ALERT_BOT_TOKEN", "")
    monkeypatch.setattr(support_health, "TECH_ALERT_CHAT_ID", "")

    readiness = support_health.build_admin_readiness(
        system_health={
            "database": {"ok": True},
            "migrations": {"pending": ["0003"], "latest": "0003"},
            "release": {"version": "stage", "commit": None},
        },
        alert_summary={"error": 1, "warning": 2},
        sync_summary={"error": 0, "stale": 1},
        recent_job_runs=[{"status": "stale"}],
        backup_status={"status": "error", "message": "Backup-файлы не найдены"},
    )

    statuses = {item["key"]: item["status"] for item in readiness["items"]}
    assert readiness["overall_status"] == "error"
    assert statuses["migrations"] == "error"
    assert statuses["operational_alerts"] == "error"
    assert statuses["sync_jobs"] == "warning"
    assert statuses["tech_alerts"] == "warning"
    assert statuses["backups"] == "error"
