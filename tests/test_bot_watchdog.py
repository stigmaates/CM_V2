import asyncio
from unittest.mock import AsyncMock

import pytest
from telegram.ext import Application, ApplicationBuilder
from telegram.request import HTTPXRequest

from app.services.bot_health import Heartbeat, diagnose, read_json
from app.services.bot_watchdog import run_check
from app.services.tech_alerts import format_tech_alert_message
from bot.health import ObservedApplication, ObservedPollingRequest


def heartbeat(**values):
    return dict(pid=42, boot_id="boot", started_at=100, last_poll_success=995, **values)


def check(data, **values):
    return diagnose(data, pid=42, uptime=900, now=1000, boot="boot", **values)


def test_idle_bot_with_empty_successful_polls_is_healthy():
    assert check(heartbeat()) is None


@pytest.mark.parametrize(
    "data,code",
    [
        ({}, "bot_heartbeat_missing"),
        ({"pid": 43, "boot_id": "boot"}, "bot_heartbeat_missing"),
        ({"pid": 42, "boot_id": "previous-boot"}, "bot_heartbeat_missing"),
        (dict(heartbeat(), last_poll_success=800), "bot_polling_stalled"),
        (heartbeat(handler_started_at=800), "bot_handler_stalled"),
        (heartbeat(queued_updates=102, last_handler_finished=800), "bot_queue_stalled"),
        (dict(heartbeat(), last_poll_success="bad"), "bot_heartbeat_invalid"),
    ],
)
def test_stalled_paths(data, code):
    assert check(data) == code


def test_startup_grace_is_not_a_failure():
    assert diagnose({}, pid=42, uptime=30, now=1000, boot="boot") is None


def exercise(state=None, *, data=None, now=10000, notify_result=True, active="active"):
    calls = []
    result = run_check(
        state or {},
        data or {},
        dict(active=active, pid=42, uptime=900),
        now=now,
        monotonic=1000,
        boot="boot",
        notify=lambda code, message: calls.append(("notify", code)) or notify_result,
        restart=lambda: calls.append(("restart",)),
        persist=lambda data: calls.append(("persist", list(data["restarts"]))),
    )
    return result, calls


def test_failed_alert_does_not_block_recovery_and_budget_is_saved_first():
    state, calls = exercise(notify_result=False)
    assert calls[-2:] == [("persist", [10000]), ("restart",)]
    assert "last_alert_at" not in state
    assert state["status"] == "restart_requested"


def test_restart_gap_and_hourly_limit_persist_across_checks():
    first, _ = exercise()
    second, calls = exercise(first, now=10060)
    assert ("restart",) not in calls
    third, calls = exercise(second, now=10600)
    assert ("restart",) in calls
    fourth, calls = exercise(third, now=11200)
    assert ("restart",) not in calls
    assert fourth["restarts"] == [10000, 10600]
    _, calls = exercise(fourth, now=13601)
    assert ("restart",) in calls


def test_manual_stop_is_respected():
    state, calls = exercise(active="inactive")
    assert state["status"] == "paused" and not calls


def test_recovery_notification_is_once_and_retried_if_delivery_failed():
    state, _ = exercise()
    state, calls = exercise(state, data=heartbeat(), notify_result=False)
    assert ("notify", "bot_recovered") in calls and "incident" in state
    state, calls = exercise(state, data=heartbeat())
    assert ("notify", "bot_recovered") in calls and "incident" not in state
    _, calls = exercise(state, data=heartbeat())
    assert not calls


def test_empty_poll_records_success_but_proxy_error_does_not(monkeypatch, tmp_path):
    clock = [100]
    hb = Heartbeat(tmp_path / "guest.json", clock=lambda: clock[0], boot="boot")

    async def run():
        request = ObservedPollingRequest(hb)
        monkeypatch.setattr(HTTPXRequest, "do_request", AsyncMock(return_value=(200, b'{"ok":true,"result":[]}')))
        await request.do_request("https://example/getUpdates", "POST")
        clock[0] = 200
        monkeypatch.setattr(HTTPXRequest, "do_request", AsyncMock(side_effect=RuntimeError("secret-token")))
        with pytest.raises(RuntimeError):
            await request.do_request("https://example/getUpdates", "POST")
        await request.shutdown()

    asyncio.run(run())
    state = read_json(hb.path)
    assert state["last_poll_success"] == 100
    assert state["last_poll_error"] == "RuntimeError"
    assert "secret-token" not in hb.path.read_text()
    assert hb.path.stat().st_mode & 0o077 == 0


def test_api_error_is_not_a_successful_poll(monkeypatch, tmp_path):
    hb = Heartbeat(tmp_path / "guest.json", boot="boot")

    async def run():
        request = ObservedPollingRequest(hb)
        monkeypatch.setattr(HTTPXRequest, "do_request", AsyncMock(return_value=(401, b'{"ok":false}')))
        await request.do_request("https://example/getUpdates", "POST")
        await request.shutdown()

    asyncio.run(run())
    assert "last_poll_success" not in read_json(hb.path)


def test_application_tracks_handler_completion_even_on_exception(monkeypatch, tmp_path):
    hb = Heartbeat(tmp_path / "guest.json", boot="boot")
    app = (
        ApplicationBuilder()
        .token("123:TEST")
        .updater(None)
        .application_class(ObservedApplication, {"heartbeat": hb})
        .build()
    )

    async def handler(self, update):
        assert read_json(hb.path)["handler_started_at"] is not None
        raise RuntimeError("handler failed")

    monkeypatch.setattr(Application, "process_update", handler)
    with pytest.raises(RuntimeError):
        asyncio.run(app.process_update(object()))
    assert read_json(hb.path)["handler_started_at"] is None
    assert read_json(hb.path)["last_handler_finished"] > 0


@pytest.mark.parametrize(
    "code,job,phrase",
    [
        ("bot_polling_stalled", "guest_telegram_bot", "Бот не отвечает гостям"),
        ("bot_recovered", "guest_telegram_bot", "Бот снова работает"),
        ("sync_error", "sync_guests_incremental", "Не удалось обновить гостей"),
        ("sync_error", "sync_balance_topups_incremental", "Не удалось обновить пополнения"),
        ("mailing_stuck", None, "Рассылка остановилась"),
        ("backup_stale", None, "Нет свежей резервной копии"),
    ],
)
def test_plain_russian_precedes_technical_details(code, job, phrase):
    text = format_tech_alert_message(dict(code=code, job_type=job, message="<unsafe>", metadata={}))
    assert phrase in text.splitlines()[0]
    assert "<unsafe>" not in text
    assert "Технические подробности" in text
