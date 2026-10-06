"""History scope, cancellation reconciliation, scheduling secrets and failure state."""

import json
import os
from datetime import UTC, datetime

import pytest

from app.integrations import gizmo_sync as sync
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_import import collect


def test_full_history_reads_all_dates_and_rechecks_old_cancellations():
    calls = []

    class API:
        def get(self, resource, params=None):
            calls.append((resource, params))
            old_session = dict(
                id=123,
                userId=10,
                startTime="2020-01-01T10:00:00Z",
                endTime="2020-01-01T11:00:00Z",
                usageSessionId=999,
                span=3500,
            )
            data = {
                "branches": [dict(id=1)],
                "paymentmethods": [dict(id=-1)],
                "users": [dict(Type=0, Model=dict(Id=10, FirstName="Test", RegistrationDate="2019-01-01T00:00:00Z"))],
                "hosts": [dict(Type=0, Model=dict(Id=5, Name="PC5", Number=5))],
                "usersessions": [dict(id=123, userId=10, hostId=5, state=2, span=3500)],
                "sessions": [old_session],
                "deposittransactions": [
                    dict(
                        id=50,
                        userId=10,
                        date="2020-01-01T10:00:00Z",
                        type=0,
                        paymentMethodId=-1,
                        branchId=1,
                        isVoid=False,
                        isVoided=True,
                        amount=500,
                    )
                ],
            }
            return {"data": data[resource], "nextCursor": None}

    result = collect(
        API(), branch_id=1, start=None, end=datetime(2026, 10, 6, tzinfo=UTC), cash_method_ids={-1}, full_history=True
    )
    assert result["sessions"][0]["date_start"] == datetime(2020, 1, 1, 10)
    assert result["topups"][0]["amount"] == 0
    assert result["scope"]["full_history"] is True and result["scope"]["start"] is None
    params = next(params for resource, params in calls if resource == "deposittransactions")
    assert "DateFrom" not in params and "DateTo" not in params


def test_credential_file_is_private_and_atomic(tmp_path):
    path = tmp_path / "sync.json"
    sync.atomic_json(path, dict(api_key="test-secret", enabled=True))
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert sync.private_json(path)["enabled"] is True
    path.chmod(0o644)
    with pytest.raises(GizmoError, match="0600"):
        sync.private_json(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        sync.private_json(link)


def test_worker_lock_prevents_overlapping_full_imports(tmp_path):
    path = tmp_path / "sync.lock"
    with sync.run_lock(path):
        with pytest.raises(GizmoError, match="already running"):
            with sync.run_lock(path):
                pytest.fail("Concurrent import acquired same lock")


@pytest.fixture
def worker(tmp_path, monkeypatch):
    sync.atomic_json(tmp_path / "sync-900001.json", dict(enabled=True, api_key="private-key"))
    (tmp_path / "server.pem").write_text("fixture-cert")
    monkeypatch.setattr(sync, "require_stage_environment", lambda: None)
    monkeypatch.setattr(
        sync,
        "read_target",
        lambda *a: dict(
            branch_id=1,
            cash_method_ids=[-1, -2],
            source=dict(address="192.0.2.1", server_name="gizmo.local", fingerprint="fixture"),
        ),
    )
    monkeypatch.setattr(sync, "GizmoClient", lambda **kw: object())
    events = []

    def collect_data(*args, **kwargs):
        assert kwargs["full_history"] is True
        assert kwargs["start"] is None
        events.append("collect")
        return dict(scope={}, counts={"sessions": 10})

    monkeypatch.setattr(sync, "collect", collect_data)
    monkeypatch.setattr(sync, "save", lambda *a: events.append("save"))

    def pulse(*args, **kwargs):
        assert kwargs["stage_gizmo_preview"] is True
        events.append("pulse")
        return dict(status="updated", guests=5)

    monkeypatch.setattr(sync, "refresh_club", pulse)
    return tmp_path, events


def test_worker_completes_only_after_storage_and_pulse(worker):
    directory, events = worker
    status = sync.synchronize(None, 900001, directory=directory)
    assert events == ["collect", "save", "pulse"]
    assert status["status"] == "complete"
    assert status["last_success_at_utc"]
    text = (directory / "status-900001.json").read_text()
    assert "private-key" not in text
    assert json.loads(text)["counts"]["sessions"] == 10


def test_worker_collection_failure_does_not_save_or_advance_success(worker, monkeypatch):
    directory, events = worker
    sync.atomic_json(directory / "status-900001.json", dict(last_success_at_utc="previous-success"))

    def failure(*args, **kwargs):
        raise RuntimeError("driver arguments may contain private-key")

    monkeypatch.setattr(sync, "collect", failure)
    with pytest.raises(RuntimeError):
        sync.synchronize(None, 900001, directory=directory)
    status = sync.private_json(directory / "status-900001.json")
    assert status["status"] == "error"
    assert status["last_success_at_utc"] == "previous-success"
    assert status["error"] == "RuntimeError"
    assert events == []


def test_pulse_failure_keeps_data_saved_marker_but_not_success(worker, monkeypatch):
    directory, events = worker
    monkeypatch.setattr(sync, "refresh_club", lambda *a, **kw: dict(status="locked"))
    with pytest.raises(GizmoError, match="Data saved"):
        sync.synchronize(None, 900001, directory=directory)
    status = sync.private_json(directory / "status-900001.json")
    assert status["status"] == "error" and status["data_saved_at_utc"]
    assert status["last_success_at_utc"] is None
    assert events == ["collect", "save"]


def test_paused_sync_performs_no_api_or_db_work(worker):
    directory, events = worker
    sync.atomic_json(directory / "sync-900001.json", dict(enabled=False, api_key="private-key"))
    assert sync.synchronize(None, 900001, directory=directory)["status"] == "paused"
    assert events == []


def test_wrong_environment_is_rejected_before_any_io(monkeypatch, tmp_path):
    def reject():
        raise ValueError("Not stage")

    monkeypatch.setattr(sync, "require_stage_environment", reject)
    with pytest.raises(ValueError, match="Not stage"):
        sync.synchronize(None, 900001, directory=tmp_path)
    assert list(tmp_path.iterdir()) == []
