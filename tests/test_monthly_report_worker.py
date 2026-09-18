from pathlib import Path

from scripts import process_monthly_reports as worker


ROOT = Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchall(self):
        return [{"id": 7}, {"id": 9}]


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_worker_processes_queued_reports_and_recovers_stale_jobs(monkeypatch):
    conn = FakeConnection()
    processed = []
    monkeypatch.setattr(worker, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        worker,
        "generate_saved_monthly_report",
        lambda report_id: processed.append(report_id) is None,
    )

    assert worker.process_monthly_reports(2) == (2, 0)
    assert processed == [7, 9]
    assert conn.committed is True
    assert conn.closed is True
    assert "status='running'" in conn.cursor_instance.executed[0][0]
    assert conn.cursor_instance.executed[1][1] == (2,)


def test_monthly_report_units_use_production_paths():
    service = (ROOT / "deploy/systemd/clubmodule-monthly-reports.service").read_text()
    timer = (ROOT / "deploy/systemd/clubmodule-monthly-reports.timer").read_text()

    assert "WorkingDirectory=/root/cm_v2/CM_V2" in service
    assert "EnvironmentFile=/root/cm_v2/CM_V2/.env" in service
    assert "scripts/process_monthly_reports.py --limit 2" in service
    assert "/root/cm_stage/CM_V2" not in service
    assert "Unit=clubmodule-monthly-reports.service" in timer
    assert "OnUnitInactiveSec=1min" in timer
