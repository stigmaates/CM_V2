from app.services import job_locks


class FakeCursor:
    def __init__(self, owner_token=None):
        self.owner_token = owner_token
        self.executed = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "INSERT INTO background_job_locks" in query:
            self.owner_token = params[3]

    def fetchone(self):
        return {"owner_token": self.owner_token}


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


def test_lock_key_includes_club_and_resource():
    assert (
        job_locks.lock_key("sync_operations_incremental", club_id=3, resource_id="x")
        == "sync_operations_incremental:club:3:resource:x"
    )


def test_acquire_job_lock_returns_acquired_lock(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(job_locks, "get_db_connection", lambda: conn)

    lock = job_locks.acquire_job_lock("sync_guests_incremental", club_id=7)

    assert lock.acquired is True
    assert lock.lock_key == "sync_guests_incremental:club:7"
    assert conn.committed is True
    assert conn.closed is True
    assert any("CREATE TABLE IF NOT EXISTS background_job_locks" in query for query, _ in cursor.executed)
    assert any("INSERT INTO background_job_locks" in query for query, _ in cursor.executed)


def test_release_job_lock_deletes_owned_lock(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(job_locks, "get_db_connection", lambda: conn)

    job_locks.release_job_lock(job_locks.JobLock("sync:club:1", "token", True))

    assert conn.committed is True
    assert any("DELETE FROM background_job_locks" in query for query, _ in cursor.executed)
