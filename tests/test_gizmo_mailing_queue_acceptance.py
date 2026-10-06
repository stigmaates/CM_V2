from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.services import mailing, outbound_policy
from scripts import verify_gizmo_mailing_queue as check
from tests.test_gizmo_live_login_setup import ready  # noqa: F401
from tests.test_guest_service_pause import AuthCursor


class QueueCursor(AuthCursor):
    def execute(self, sql, params=()):
        return super().execute(sql.replace("NOW()", "CURRENT_TIMESTAMP"), params)

    def executemany(self, sql, values):
        for params in values:
            self.execute(sql, params)


@pytest.fixture
def queue_ready(ready, monkeypatch):  # noqa: F811
    from scripts import check_gizmo_stage_telegram

    monkeypatch.setattr(check_gizmo_stage_telegram, "BOT_TOKEN", "stage-test-token")
    monkeypatch.setattr(check.worker, "BOT_TOKEN", "stage-test-token")
    conn, directory = ready
    monkeypatch.setattr(conn, "cursor", lambda: QueueCursor(conn))
    conn.db.executescript("""
      CREATE TABLE mailings(id INTEGER PRIMARY KEY,club_id INT,segment_id INT,filters_json TEXT,message_text TEXT,parse_mode TEXT,status TEXT,recipients_count INT,started_at TEXT,finished_at TEXT,success_count INT DEFAULT 0,failed_count INT DEFAULT 0);
      CREATE TABLE mailing_recipients(id INTEGER PRIMARY KEY,mailing_id INT,guest_id INT,telegram_id INT,message_text TEXT,status TEXT,error_text TEXT,sent_at TEXT);
      CREATE TABLE mailing_attachments(id INTEGER PRIMARY KEY,mailing_id INT,file_type TEXT,file_path TEXT,original_name TEXT);
    """)
    conn.db.execute("INSERT INTO guests(club_id,guest_id,fio) VALUES(?,?,?)", (check.CLUB, check.GUEST, check.NAME))
    conn.commit()
    monkeypatch.setattr(check, "get_db_connection", lambda: conn)
    monkeypatch.setattr(check, "require_stage_environment", lambda: None)
    monkeypatch.setattr(check, "verify_bot", lambda: None)
    monkeypatch.setattr(mailing, "_ensure_mailing_recipient_message_column", lambda cur: None)
    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: True)
    monkeypatch.setattr(check.worker, "table_has_column", lambda *args: True)
    monkeypatch.setattr(check.worker, "start_job_run", lambda *args, **kwargs: 1)
    monkeypatch.setattr(check.worker, "finish_job_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(check.worker.time, "sleep", lambda *args: None)

    @contextmanager
    def lock(*args, **kwargs):
        yield SimpleNamespace(acquired=True)

    monkeypatch.setattr(check.worker, "job_lock", lock)
    sent = []

    def transport(method, payload, files=None):
        outbound_policy.ensure_outbound_allowed()
        assert conn.db.execute("SELECT service_enabled FROM clubs WHERE club_id=?", (check.CLUB,)).fetchone()[0] == 1
        sent.append(payload)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 777}})

    monkeypatch.setattr(check.worker, "tg_request", transport)
    yield conn, directory, sent


def test_real_queue_pause_delivery_requeue_and_cleanup(queue_ready):
    conn, directory, sent = queue_ready
    report = check.run(directory=directory)
    assert report["status"] == "complete"
    assert report["disabled_blocks_delivery"] and report["retry_did_not_resend"]
    assert report["telegram_message_id"] == 777
    assert [x["chat_id"] for x in sent] == [check.RECIPIENT]
    assert conn.records("mailing_recipients")[0]["status"] == "sent"
    assert conn.records("clubs")[1]["service_enabled"] == 0
    assert conn.records("guests")[0]["telegram_id"] is None
    with pytest.raises(ValueError):
        outbound_policy.ensure_outbound_allowed()
    assert check.run(directory=directory)["reused_report"]
    assert len(sent) == 1


def test_unknown_delivery_never_retries_and_closes_fixture(queue_ready, monkeypatch):
    conn, directory, sent = queue_ready

    def timeout(*args):
        raise httpx.ReadTimeout("secret URL")

    monkeypatch.setattr(check.worker, "tg_request", timeout)
    with pytest.raises(ValueError, match="не подтверждена"):
        check.run(directory=directory)
    assert conn.records("clubs")[1]["service_enabled"] == 0
    assert conn.records("mailing_recipients")[0]["status"] == "failed"
    assert "secret" not in conn.records("mailing_recipients")[0]["error_text"]
    with pytest.raises(ValueError, match="Предыдущая попытка"):
        check.run(directory=directory)
    assert not sent


def test_guard_refuses_unapproved_recipient_even_if_queue_wrong(queue_ready, monkeypatch):
    conn, directory, sent = queue_ready
    create = check.create_mailing_for_recipients

    def corrupt(conn, club, recipients, *args, **kwargs):
        recipients[0]["telegram_id"] = 999
        return create(conn, club, recipients, *args, **kwargs)

    monkeypatch.setattr(check, "create_mailing_for_recipients", corrupt)
    with pytest.raises(ValueError, match="не подтверждена"):
        check.run(directory=directory)
    assert not sent
    assert conn.records("clubs")[1]["service_enabled"] == 0


def test_active_fixture_rejected_before_telegram(queue_ready, monkeypatch):
    conn, directory, sent = queue_ready
    conn.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (check.CLUB,))
    conn.commit()
    monkeypatch.setattr(check, "verify_bot", lambda: pytest.fail("must not contact Telegram"))
    with pytest.raises(ValueError, match="Сначала завершите"):
        check.run(directory=directory)
    assert not conn.records("mailings")
