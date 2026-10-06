from types import SimpleNamespace

import pytest

from app.services import outbound_policy
from scripts import check_gizmo_stage_telegram as check


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(check, "require_stage_environment", lambda: None)
    monkeypatch.setattr(check, "BOT_TOKEN", "stage-test-token")
    monkeypatch.setattr(check, "BOT_USERNAME", "stage_test_bot")
    monkeypatch.setattr(check.process_mailings, "BOT_TOKEN", "stage-test-token")
    monkeypatch.setattr(check, "dotenv_values", lambda path: {"BOT_TOKEN": "production-test-token"})
    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: True)
    monkeypatch.delenv("ALLOW_STAGE_MANUAL_MAILINGS", raising=False)
    sent = []
    responses = {
        "getMe": {"username": "stage_test_bot"},
        "getChat": {"id": 123, "type": "private", "username": "stigmaates"},
    }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json):
            method = url.rsplit("/", 1)[1]
            assert method in ("getMe", "getChat")
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": responses[method]})

    def send(telegram_id, text, parse_mode, attachments):
        outbound_policy.ensure_outbound_allowed()
        sent.append(telegram_id)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 77}})

    monkeypatch.setattr(check.httpx, "Client", Client)
    monkeypatch.setattr(check.process_mailings, "send_single_message", send)
    return responses, sent


def test_authorized_delivery_is_single_recipient_and_override_is_temporary(setup):
    responses, sent = setup
    with pytest.raises(ValueError):
        outbound_policy.ensure_outbound_allowed()
    assert check.run(123)["status"] == "sent"
    assert sent == [123]
    with pytest.raises(ValueError):
        outbound_policy.ensure_outbound_allowed()


@pytest.mark.parametrize(
    "chat",
    [
        None,
        {"id": 123, "type": "private", "username": "another"},
        {"id": 124, "type": "private", "username": "stigmaates"},
        {"id": 123, "type": "supergroup", "username": "stigmaates"},
    ],
)
def test_never_sends_to_unverified_account(setup, chat):
    responses, sent = setup
    responses["getChat"] = chat
    assert check.run(123)["status"] == "recipient_not_verified"
    assert sent == []


def test_production_bot_is_rejected_before_network(setup, monkeypatch):
    monkeypatch.setattr(check, "dotenv_values", lambda path: {"BOT_TOKEN": "stage-test-token"})
    with pytest.raises(ValueError, match="отдельный токен"):
        check.run(123)
    assert setup[1] == []


def test_unknown_delivery_is_not_retried_and_override_closes(setup, monkeypatch):
    def timeout(*args):
        raise check.httpx.ReadTimeout("secret URL must not be printed")

    monkeypatch.setattr(check.process_mailings, "send_single_message", timeout)
    report = check.run(123)
    assert report["status"] == "delivery_unknown"
    assert "secret" not in str(report)
    with pytest.raises(ValueError):
        outbound_policy.ensure_outbound_allowed()


def test_api_does_not_log_bot_token_when_application_enables_info(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="httpx")

    class Client:
        def post(self, url, json):
            logging.getLogger("httpx").info("HTTP Request: POST %s", url)
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": {"id": 123}})

    assert check.api(Client(), "getMe", {}) == {"id": 123}
    assert not caplog.records
