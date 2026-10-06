"""History scope, cancellation reconciliation, scheduling secrets and failure state."""

import json
import os
from datetime import UTC, datetime

import pytest

from app.integrations import gizmo_sync as sync
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_import import collect


@pytest.mark.parametrize(
    "invalid_end,reason",
    [
        ("2020-01-01T10:00:00Z", "end_equals_start"),
        ("2020-01-01T09:59:00Z", "end_before_start"),
    ],
)
def test_full_history_reads_all_dates_and_rechecks_old_cancellations(invalid_end, reason):
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
                "sessions": [old_session, dict(old_session, id=124, endTime=invalid_end)],
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
    assert len(result["sessions"]) == 1
    assert result["counts"]["sessions_invalid_time_skipped"] == 1
    assert result["rejected_sessions"] == [
        dict(id=124, reason=reason, start_utc="2020-01-01T10:00:00", end_utc=invalid_end.removesuffix("Z"))
    ]
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
        sync, "read_club", lambda *a: dict(integration_provider="gizmo", service_enabled=0, integration_ready=0)
    )
    monkeypatch.setattr(
        sync,
        "read_target",
        lambda *a, **kw: dict(
            branch_id=1,
            cash_method_ids=[-1, -2],
            source=dict(address="192.0.2.1", server_name="gizmo.local", fingerprint="fixture"),
        ),
    )
    monkeypatch.setattr(sync, "GizmoClient", lambda **kw: object())
    events = []
    monkeypatch.setattr(sync, "start_job_run", lambda *a, **kw: 123)
    monkeypatch.setattr(sync, "finish_job_run", lambda *a, **kw: None)

    def collect_data(*args, **kwargs):
        assert kwargs["full_history"] is True
        assert kwargs["start"] is None
        events.append("collect")
        return dict(scope={}, counts={"sessions": 10})

    monkeypatch.setattr(sync, "collect", collect_data)
    monkeypatch.setattr(sync, "save", lambda *a, **kw: events.append("save"))
    monkeypatch.setattr(
        sync, "rebuild_club_portrait", lambda *a: events.append("portrait") or dict(status="updated", guests=5)
    )

    def pulse(*args, **kwargs):
        assert kwargs["stage_gizmo_preview"] is True
        events.append("pulse")
        return dict(status="updated", guests=5)

    monkeypatch.setattr(sync, "refresh_club", pulse)
    return tmp_path, events


def test_worker_completes_only_after_storage_and_pulse(worker):
    directory, events = worker
    status = sync.synchronize(None, 900001, directory=directory)
    assert events == ["collect", "save", "portrait", "pulse"]
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
    assert events == ["collect", "save", "portrait"]


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


def test_portrait_failure_does_not_mark_sync_success_or_run_pulse(worker, monkeypatch):
    directory, events = worker
    monkeypatch.setattr(sync, "rebuild_club_portrait", lambda *a: dict(status="failed"))
    with pytest.raises(GizmoError, match="CRM portrait"):
        sync.synchronize(None, 900001, directory=directory)
    status = sync.private_json(directory / "status-900001.json")
    assert status["status"] == "error" and status["data_saved_at_utc"]
    assert status["last_success_at_utc"] is None
    assert "pulse" not in events


def test_worker_records_common_job_and_safe_failure(worker, monkeypatch):
    directory, events = worker
    starts, ends = [], []
    monkeypatch.setattr(sync, "start_job_run", lambda *a, **kw: starts.append((a, kw)) or 456)
    monkeypatch.setattr(sync, "finish_job_run", lambda *a, **kw: ends.append((a, kw)))
    result = sync.synchronize(None, 900001, directory=directory)
    assert starts[0][0] == ("sync_gizmo",)
    assert starts[0][1]["club_id"] == 900001
    assert ends[0][0] == (456, "success")
    assert ends[0][1]["metadata"]["pulse"]["status"] == "updated"
    assert result["finished_at_utc"] == result["last_success_at_utc"]
    assert sync.private_json(directory / "sync-900001.json")["certificate_pem"] == "fixture-cert"

    def broken(*a, **kw):
        raise RuntimeError("private-key")

    monkeypatch.setattr(sync, "read_target", broken)
    with pytest.raises(RuntimeError):
        sync.synchronize(None, 900001, directory=directory)
    assert ends[-1][0] == (456, "error")
    assert ends[-1][1]["error_text"] == "RuntimeError"
    assert "private-key" not in json.dumps(ends)


def test_worker_due_check_happens_under_club_lock_and_skips_job(worker, monkeypatch):
    directory, events = worker
    sync.atomic_json(
        directory / "status-900001.json", {"status": "complete", "last_success_at_utc": datetime.now(UTC).isoformat()}
    )
    monkeypatch.setattr(
        sync, "start_job_run", lambda *a, **kw: pytest.fail("A skipped job must not hide latest success")
    )
    assert sync.synchronize(None, 900001, directory=directory, only_if_due=True)["status"] == "not_due"
    assert events == []


def test_worker_uses_per_club_certificate_without_shared_file(worker, monkeypatch):
    directory, events = worker
    (directory / "server.pem").unlink()
    credentials = sync.private_json(directory / "sync-900001.json")
    credentials["certificate_pem"] = "club-specific-cert"
    sync.atomic_json(directory / "sync-900001.json", credentials)

    def client(**kwargs):
        assert kwargs["certificate_pem"] == "club-specific-cert"
        return object()

    monkeypatch.setattr(sync, "GizmoClient", client)
    assert sync.synchronize(None, 900001, directory=directory)["status"] == "complete"
