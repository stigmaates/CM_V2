from app.services import job_runs


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.lastrowid = 42

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_start_job_run_creates_running_record(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(job_runs, "get_db_connection", lambda: conn)

    job_run_id = job_runs.start_job_run(
        "sync_guests_incremental",
        club_id=7,
        metadata={"source": "langame"},
    )

    assert job_run_id == 42
    assert conn.committed is True
    assert conn.closed is True
    assert any("CREATE TABLE IF NOT EXISTS background_job_runs" in query for query, _ in cursor.executed)
    assert any("INSERT INTO background_job_runs" in query for query, _ in cursor.executed)


def test_finish_job_run_updates_status(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(job_runs, "get_db_connection", lambda: conn)

    job_runs.finish_job_run(
        42,
        "success",
        rows_received=10,
        rows_saved=8,
        metadata={"filtered": 8},
    )

    assert conn.committed is True
    assert conn.closed is True
    assert any("UPDATE background_job_runs" in query for query, _ in cursor.executed)


def test_latest_job_runs_are_grouped_by_club(monkeypatch):
    rows = [
        {"club_id": 1, "job_type": "sync_guests_incremental", "status": "success"},
        {"club_id": 1, "job_type": "sync_sessions_incremental", "status": "error"},
        {"club_id": 2, "job_type": "sync_guests_incremental", "status": "running"},
    ]
    cursor = FakeCursor(rows=rows)
    conn = FakeConnection(cursor)
    monkeypatch.setattr(job_runs, "get_db_connection", lambda: conn)

    result = job_runs.get_latest_job_runs_by_club([
        "sync_guests_incremental",
        "sync_sessions_incremental",
    ])

    assert result[1]["sync_guests_incremental"]["status"] == "success"
    assert result[1]["sync_sessions_incremental"]["status"] == "error"
    assert result[2]["sync_guests_incremental"]["status"] == "running"
    assert conn.closed is True
