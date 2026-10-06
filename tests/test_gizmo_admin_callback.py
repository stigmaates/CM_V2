import json

import httpx
import pytest

from app.integrations.gizmo_sync import atomic_json, private_json
from app.services import prize_claims
from scripts import verify_gizmo_admin_callback as callback
from tests.test_gizmo_reward_journey import imported, ready, wallets  # noqa: F401

REAL_SEND_CLAIM = callback.send_claim


@pytest.fixture
def stage(ready, tmp_path, monkeypatch):  # noqa: F811
    from scripts.verify_gizmo_stage_lifecycle import TEST_NAME

    ready.db.executescript("""
        ALTER TABLE clubs ADD COLUMN name TEXT;
        ALTER TABLE clubs ADD COLUMN owner_id INT;
        ALTER TABLE guest_prize_claims ADD COLUMN issued_by_telegram_id INT;
    """)
    ready.db.execute(
        "INSERT INTO clubs (club_id,integration_provider,integration_ready,service_enabled,name) VALUES (?,'gizmo',1,0,?)",
        (callback.CLUB, TEST_NAME),
    )
    ready.db.execute(
        "INSERT INTO guests (club_id,guest_id,fio) VALUES (?,?,?)", (callback.CLUB, callback.GUEST, callback.NAME)
    )
    ready.commit()
    atomic_json(tmp_path / "acceptance-900001.json", dict(test_club_id=callback.CLUB))
    atomic_json(tmp_path / f"sync-{callback.CLUB}.json", dict(enabled=False))
    monkeypatch.setattr(callback, "require_stage_environment", lambda: None)
    monkeypatch.setattr(callback, "get_db_connection", lambda: ready)
    monkeypatch.setattr(callback, "verify_poller", lambda: None)
    monkeypatch.setattr(
        callback.probe, "run", lambda: dict(status="ready_for_callback_setup", bot_username="cm_delivery_test_bot")
    )
    sent = []

    def send(claim_id, report, path):
        sent.append(claim_id)
        return dict(ok=True, message_id=7)

    monkeypatch.setattr(callback, "send_claim", send)
    return ready, tmp_path, sent


def test_setup_repeat_callback_finish_and_cleanup(stage):
    conn, directory, sent = stage
    report = callback.run("setup", directory=directory)
    claim_id = report["claim_id"]
    assert report["status"] == "waiting_for_click"
    assert sent == [claim_id]
    assert callback.run("setup", directory=directory)["reused"]
    assert sent == [claim_id]
    assert callback.run("finish", directory=directory)["status"] == "waiting_for_click"
    # Exercise the real callback service; live Telegram itself is the manual stage check.
    assert prize_claims.mark_prize_claim_issued_by_telegram(
        claim_id, callback.RECIPIENT, callback.RECIPIENT, "@stigmaates"
    )["ok"]
    result = callback.run("finish", directory=directory)
    assert result["live_callback_verified"] and result["repeat_idempotent"]
    assert result["test_claim_removed"] and result["balances_unchanged"]
    assert not conn.records("guest_prize_claims")
    assert callback.run("finish", directory=directory)["reused"]
    assert next(r for r in conn.records("clubs") if r["club_id"] == callback.CLUB)["service_enabled"] == 0


def test_unknown_delivery_never_resends_and_can_cancel(stage, monkeypatch):
    conn, directory, _ = stage
    calls = []

    def fail(claim_id, report, path):
        calls.append(claim_id)
        report["delivery_attempted"] = True
        atomic_json(path, report)
        raise ValueError("uncertain delivery")

    monkeypatch.setattr(callback, "send_claim", fail)
    with pytest.raises(ValueError, match="uncertain"):
        callback.run("setup", directory=directory)
    assert callback.run("setup", directory=directory)["reused"]
    assert len(calls) == 1
    assert callback.run("cancel", directory=directory)["status"] == "cancelled"
    assert not conn.records("guest_prize_claims")


def test_other_actor_cannot_count_as_acceptance(stage):
    conn, directory, _ = stage
    report = callback.run("setup", directory=directory)
    conn.db.execute(
        "UPDATE guest_prize_claims SET status='issued',issued_by_telegram_id=99,issued_at='2026-10-06 20:00:00' WHERE id=?",
        (report["claim_id"],),
    )
    conn.commit()
    with pytest.raises(ValueError, match="Telegram"):
        callback.run("finish", directory=directory)
    assert len(conn.records("guest_prize_claims")) == 1


def test_guarded_sender_uses_real_notification(stage, monkeypatch):
    conn, directory, _ = stage
    report = callback.run("setup", directory=directory)
    path = directory / "admin-callback-acceptance.json"
    sent = []
    monkeypatch.setattr(prize_claims, "CM_BONUS_BOT_TOKEN", "fake-test-token")
    monkeypatch.setattr(callback.probe, "CM_BONUS_BOT_TOKEN", "fake-test-token")

    def transport(client, request, *args, **kwargs):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", transport)
    assert REAL_SEND_CLAIM(report["claim_id"], report, path) == {"ok": True, "message_id": 88}
    assert len(sent) == 1 and sent[0]["chat_id"] == str(callback.RECIPIENT)
    assert private_json(path)["delivery_attempted"]
    assert conn.records("guest_prize_claims")[0]["status"] == "notified"


def test_sender_rejects_another_claim_before_http(stage):
    _, directory, _ = stage
    with pytest.raises(ValueError, match="тестовой"):
        REAL_SEND_CLAIM(999999, {}, directory / "unused.json")


def test_foreign_recipient_cannot_escape_transport_guard(stage, monkeypatch):
    _, directory, _ = stage
    report = callback.run("setup", directory=directory)
    monkeypatch.setattr(prize_claims, "CM_BONUS_BOT_TOKEN", "fake-test-token")
    monkeypatch.setattr(callback.probe, "CM_BONUS_BOT_TOKEN", "fake-test-token")

    def forbidden_transport(*args, **kwargs):
        pytest.fail("Forbidden recipient reached transport")

    monkeypatch.setattr(httpx.Client, "send", forbidden_transport)

    def altered_notify(claim_id):
        with httpx.Client() as client:
            client.post(
                "https://api.telegram.org/botfake-test-token/sendMessage", json={"chat_id": 999, "text": "wrong"}
            )

    monkeypatch.setattr(prize_claims, "notify_prize_claim_admin_chat", altered_notify)
    with pytest.raises(ValueError, match="запрещена"):
        REAL_SEND_CLAIM(report["claim_id"], report, directory / "admin-callback-acceptance.json")
