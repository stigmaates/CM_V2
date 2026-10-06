import pytest

from scripts import check_gizmo_stage_admin_bot as probe


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(probe, "require_stage_environment", lambda: None)
    monkeypatch.setattr(
        probe, "dotenv_values", lambda path: dict(BOT_TOKEN="prod-guest", CM_BONUS_BOT_TOKEN="prod-admin")
    )
    monkeypatch.setattr(probe, "CM_BONUS_BOT_TOKEN", "stage-admin")
    monkeypatch.setattr(probe, "BOT_TOKEN", "stage-guest")
    calls = []

    def api(client, method, payload):
        calls.append((method, payload))
        if method == "getMe":
            return dict(is_bot=True, username="test_admin_bot")
        return dict(id=328908187, type="private", username="stigmaates")

    monkeypatch.setattr(probe, "api", api)
    return calls


@pytest.mark.parametrize("token", ["prod-guest", "prod-admin", "stage-guest", ""])
def test_rejects_nonisolated_admin_bot_before_network(configured, monkeypatch, token):
    monkeypatch.setattr(probe, "CM_BONUS_BOT_TOKEN", token)
    assert probe.run()["status"] == "separate_admin_bot_required"
    assert configured == []


def test_probe_only_reads_authorized_recipient(configured):
    assert probe.run()["status"] == "ready_for_callback_setup"
    assert configured == [("getMe", {}), ("getChat", {"chat_id": 328908187})]


def test_unverified_recipient_needs_start(configured, monkeypatch):
    monkeypatch.setattr(
        probe,
        "api",
        lambda client, method, payload: dict(is_bot=True, username="test_admin_bot") if method == "getMe" else None,
    )
    report = probe.run()
    assert report["status"] == "needs_start"
    assert report["bot_link"] == "https://t.me/test_admin_bot"


def test_api_rejects_sends_and_other_recipients():
    for method, payload in (("sendMessage", {"chat_id": 328908187}), ("getUpdates", {}), ("getChat", {"chat_id": 1})):
        with pytest.raises(ValueError):
            probe.api(None, method, payload)
