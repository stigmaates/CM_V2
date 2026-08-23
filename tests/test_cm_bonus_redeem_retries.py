from datetime import timedelta

from app.services import cm_bonuses
from app.services.cm_bonuses import _redeem_notification_retry_delay


class FakeCursor:
    rowcount = 1

    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_redeem_notification_retry_backoff():
    assert _redeem_notification_retry_delay(1) == timedelta(minutes=1)
    assert _redeem_notification_retry_delay(2) == timedelta(minutes=5)
    assert _redeem_notification_retry_delay(3) == timedelta(minutes=15)
    assert _redeem_notification_retry_delay(4) == timedelta(minutes=60)
    assert _redeem_notification_retry_delay(20) == timedelta(minutes=60)


def test_retry_updates_notification_only_and_never_touches_balance(monkeypatch):
    conn = FakeConnection()
    request = {
        "id": 17,
        "club_id": 2,
        "guest_id": 9001,
        "guest_name": "Иванов Иван Иванович",
        "guest_phone": "9991112233",
        "amount": 300,
        "notify_attempts": 2,
    }

    monkeypatch.setattr(cm_bonuses, "_claim_cm_bonus_redeem_notification", lambda request_id: request)
    monkeypatch.setattr(
        cm_bonuses,
        "_notify_admin_chat",
        lambda guest, amount, request_id: (True, 777, None, "-100123"),
    )
    monkeypatch.setattr(cm_bonuses, "get_db_connection", lambda: conn)
    monkeypatch.setattr(cm_bonuses, "ensure_cm_bonus_tables", lambda cursor: None)
    monkeypatch.setattr(
        cm_bonuses,
        "add_cm_bonus_transaction",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("balance must not change during retry")),
    )

    result = cm_bonuses.notify_cm_bonus_redeem_request(17)

    assert result["ok"] is True
    assert result["message_id"] == 777
    assert conn.committed is True
    assert conn.closed is True
    update_query, update_params = conn.cursor_obj.executed[-1]
    assert "UPDATE cm_bonus_redeem_requests" in update_query
    assert update_params[0] == "notified"
    assert update_params[2] == 777


def test_failed_retry_schedules_next_attempt(monkeypatch):
    conn = FakeConnection()
    request = {
        "id": 18,
        "club_id": 2,
        "guest_id": 9002,
        "guest_name": "Петров Петр Петрович",
        "guest_phone": "9991112244",
        "amount": 500,
        "notify_attempts": 3,
    }

    monkeypatch.setattr(cm_bonuses, "_claim_cm_bonus_redeem_notification", lambda request_id: request)
    monkeypatch.setattr(
        cm_bonuses,
        "_notify_admin_chat",
        lambda guest, amount, request_id: (False, None, "Telegram timeout", "-100123"),
    )
    monkeypatch.setattr(cm_bonuses, "get_db_connection", lambda: conn)
    monkeypatch.setattr(cm_bonuses, "ensure_cm_bonus_tables", lambda cursor: None)

    result = cm_bonuses.notify_cm_bonus_redeem_request(18)

    assert result["ok"] is False
    assert result["next_notify_attempt_at"] is not None
    update_params = conn.cursor_obj.executed[-1][1]
    assert update_params[0] == "notify_failed"
    assert update_params[3] == "Telegram timeout"
    assert update_params[4] is not None
