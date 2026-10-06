"""Service activation, pause during import, freshness and explicit refresh lifecycle."""

from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import gizmo_lifecycle as lifecycle
from app.integrations import gizmo_onboarding as onboarding
from app.integrations import gizmo_sync as sync
from app.integrations.gizmo import GizmoError
from tests.test_gizmo_onboarding import api, queued
from tests.test_gizmo_onboarding import certificate as certificate
from tests.test_gizmo_onboarding import setup as setup


@pytest.fixture
def imported(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    api(monkeypatch)
    sync.synchronize(conn, 900001, directory=directory)
    monkeypatch.setattr(lifecycle, "require_stage_environment", lambda: None)
    return conn, directory


def test_initial_activation_service_cycles_disable_refresh_and_resume(imported):
    conn, directory = imported
    lifecycle.set_service(conn, 900001, True, directory=directory)
    assert conn.records("clubs")[0]["integration_ready"] == 1
    assert conn.records("clubs")[0]["service_enabled"] == 1
    assert sync.synchronize(conn, 900001, directory=directory, only_if_due=True)["status"] == "complete"
    lifecycle.set_service(conn, 900001, False, directory=directory)
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "paused"
    credentials = sync.private_json(directory / "sync-900001.json")
    onboarding.queue_setup(conn, 900001, credentials["connection"], directory=directory)
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "complete"
    assert conn.records("clubs")[0]["service_enabled"] == 0
    # Refresh is one-shot; disabled clubs never keep syncing automatically.
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "paused"
    lifecycle.set_service(conn, 900001, True, directory=directory)
    assert sync.synchronize(conn, 900001, directory=directory, only_if_due=True)["status"] == "complete"
    assert len(conn.records("guest_sessions")) == 1


@pytest.mark.parametrize("failure", ["old", "future", "error", "portrait", "pulse", "counts", "source", "paused"])
def test_activation_refuses_unready_history(imported, failure):
    conn, directory = imported
    path = directory / "status-900001.json"
    state = sync.private_json(path)
    if failure in {"old", "future"}:
        state["last_success_at_utc"] = (datetime.now(UTC) + timedelta(hours=-2 if failure == "old" else 2)).isoformat()
    elif failure == "error":
        state["status"] = "error"
    elif failure in {"portrait", "pulse"}:
        state[failure]["status"] = "failed"
    elif failure == "counts":
        state["counts"].pop("sessions")
    else:
        credentials_path = directory / "sync-900001.json"
        credentials = sync.private_json(credentials_path)
        if failure == "source":
            credentials["connection"]["address"] = "192.0.2.99"
        else:
            credentials["enabled"] = False
        sync.atomic_json(credentials_path, credentials)
    sync.atomic_json(path, state)
    with pytest.raises(GizmoError):
        lifecycle.set_service(conn, 900001, True, directory=directory)
    assert conn.records("clubs")[0]["service_enabled"] == 0
    assert conn.records("clubs")[0]["integration_ready"] == 0


def test_activation_checks_real_saved_references(imported):
    conn, directory = imported
    conn.db.execute("UPDATE guest_sessions SET uuid='nonexistent'")
    conn.commit()
    with pytest.raises(GizmoError, match="некорректные"):
        lifecycle.set_service(conn, 900001, True, directory=directory)
    assert conn.records("clubs")[0]["service_enabled"] == 0


@pytest.mark.parametrize("when", ["page", "before_save"])
def test_disable_during_collection_cannot_commit_an_import(imported, monkeypatch, when):
    conn, directory = imported
    lifecycle.set_service(conn, 900001, True, directory=directory)
    original_collect = sync.collect
    saves = []
    original_save = sync.save

    def collect(*args, **kwargs):
        if when == "page":
            lifecycle.set_service(conn, 900001, False, directory=directory)
        result = original_collect(*args, **kwargs)
        if when == "before_save":
            lifecycle.set_service(conn, 900001, False, directory=directory)
        return result

    def save(*args, **kwargs):
        original_save(*args, **kwargs)
        saves.append(True)

    monkeypatch.setattr(sync, "collect", collect)
    monkeypatch.setattr(sync, "save", save)
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "paused"
    assert saves == []
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "paused"


def test_activation_cannot_race_running_worker(imported):
    conn, directory = imported
    with sync.run_lock(directory / "sync-900001.lock"):
        with pytest.raises(GizmoError, match="already running"):
            lifecycle.set_service(conn, 900001, True, directory=directory)
    assert conn.records("clubs")[0]["service_enabled"] == 0


def test_production_activation_remains_blocked(imported, monkeypatch):
    conn, directory = imported

    def reject():
        raise ValueError("not isolated stage")

    monkeypatch.setattr(lifecycle, "require_stage_environment", reject)
    with pytest.raises(ValueError):
        lifecycle.set_service(conn, 900001, True, directory=directory)
    assert conn.records("clubs")[0]["service_enabled"] == 0
