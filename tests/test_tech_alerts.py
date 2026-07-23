from datetime import UTC, datetime, timedelta

from app.services import tech_alerts


class _Response:
    status_code = 200

    def json(self):
        return {"ok": True, "result": {"message_id": 42}}


class _Cursor:
    def __init__(self, last_sent_at=None):
        self.last_sent_at = last_sent_at
        self.executed = []
        self.recorded = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.strip().startswith("INSERT INTO operational_alert_notifications"):
            self.recorded = True

    def fetchone(self):
        if self.last_sent_at is None:
            return None
        return {"last_sent_at": self.last_sent_at}


class _Connection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _alert(**overrides):
    alert = {
        "severity": "error",
        "code": "sync_error",
        "message": "Гости: последний запуск завершился статусом error",
        "club_id": 7,
        "club_name": "Stage Club",
        "job_type": "sync_guests_incremental",
        "age_minutes": 15,
        "metadata": {"error_text": "boom"},
    }
    alert.update(overrides)
    return alert


def test_build_alert_key_is_stable_for_same_alert():
    first = tech_alerts.build_alert_key(_alert())
    second = tech_alerts.build_alert_key(_alert(message="changed text"))

    assert first == second
    assert len(first) == 64


def test_build_alert_key_ignores_background_job_run_id():
    first = tech_alerts.build_alert_key(_alert(metadata={"job_run_id": 101, "error_text": "403"}))
    second = tech_alerts.build_alert_key(_alert(metadata={"job_run_id": 102, "error_text": "403"}))

    assert first == second


def test_format_tech_alert_message_escapes_html():
    message = tech_alerts.format_tech_alert_message(_alert(club_name="<club>", metadata={"error_text": "<bad>"}))

    assert "ClubModule: критическое предупреждение" in message
    assert "&lt;club&gt;" in message
    assert "&lt;bad&gt;" in message


def test_send_telegram_message_posts_payload():
    calls = []

    def http_post(url, payload):
        calls.append((url, payload))
        return _Response()

    ok, error = tech_alerts.send_telegram_message(
        "hello",
        token="token",
        chat_id="-1",
        http_post=http_post,
    )

    assert ok is True
    assert error is None
    assert calls[0][0].endswith("/sendMessage")
    assert calls[0][1]["chat_id"] == "-1"


def test_send_telegram_message_uses_dedicated_proxy_only(monkeypatch):
    client_kwargs = []

    class _Client:
        def __init__(self, **kwargs):
            client_kwargs.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            return _Response()

    monkeypatch.setattr(tech_alerts.httpx, "Client", _Client)

    monkeypatch.setattr(tech_alerts, "TECH_ALERT_PROXY_URL", "")
    ok, error = tech_alerts.send_telegram_message("hello", token="token", chat_id="-1")

    assert ok is True
    assert error is None
    assert "proxy" not in client_kwargs[-1]

    monkeypatch.setattr(tech_alerts, "TECH_ALERT_PROXY_URL", "http://alerts-proxy:8080")
    ok, error = tech_alerts.send_telegram_message("hello", token="token", chat_id="-1")

    assert ok is True
    assert error is None
    assert client_kwargs[-1]["proxy"] == "http://alerts-proxy:8080"


def test_send_test_alert_posts_explicit_test_message(monkeypatch):
    messages = []

    monkeypatch.setattr(
        tech_alerts,
        "send_telegram_message",
        lambda message, http_post=None: (messages.append(message) is None, None),
    )

    ok, error = tech_alerts.send_test_alert()

    assert ok is True
    assert error is None
    assert "тест технических алертов" in messages[0]


def test_send_operational_alerts_sends_and_records(monkeypatch):
    cursor = _Cursor()
    conn = _Connection(cursor)
    sent_messages = []

    monkeypatch.setattr(tech_alerts, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        tech_alerts,
        "send_telegram_message",
        lambda message, http_post=None: (sent_messages.append(message) is None, None),
    )

    result = tech_alerts.send_operational_alerts([_alert(), _alert(severity="warning")])

    assert result["critical"] == 1
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == []
    assert cursor.recorded is True
    assert conn.commits == 1
    assert conn.closed is True
    assert len(sent_messages) == 1


def test_send_operational_alerts_skips_recent_duplicate(monkeypatch):
    cursor = _Cursor(last_sent_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10))
    conn = _Connection(cursor)

    monkeypatch.setattr(tech_alerts, "get_db_connection", lambda: conn)

    result = tech_alerts.send_operational_alerts([_alert()], cooldown_minutes=60)

    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert cursor.recorded is False
