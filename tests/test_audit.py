from app.services.audit import record_audit_event


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class FailingConnection(FakeConnection):
    def cursor(self):
        raise RuntimeError("db unavailable")


def test_record_audit_event_writes_event(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr("app.services.audit.get_db_connection", lambda: conn)

    record_audit_event(
        action="owner.test",
        club_id=10,
        entity_type="thing",
        entity_id=25,
        details={"enabled": True},
        actor_user_id=7,
        actor_role="owner",
    )

    assert conn.committed is True
    assert conn.closed is True
    assert len(conn.cursor_obj.calls) == 1

    params = conn.cursor_obj.calls[0][1]
    assert params[0] == 10
    assert params[1] == 7
    assert params[2] == "owner"
    assert params[3] == "owner.test"
    assert params[4] == "thing"
    assert params[5] == "25"
    assert '"enabled": true' in params[6]


def test_record_audit_event_is_best_effort(monkeypatch):
    monkeypatch.setattr("app.services.audit.get_db_connection", lambda: FailingConnection())

    record_audit_event(action="owner.test")
