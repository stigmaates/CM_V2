"""Cross-club scheduling, crash recovery, provider monitoring and bounded GET retries."""

import json
import ssl
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import gizmo
from app.integrations import gizmo_scheduler as scheduler
from app.integrations import gizmo_sync as sync
from app.integrations.sync_jobs import GIZMO_SYNC_JOB, LANGAME_SYNC_JOBS
from app.routes.admin import dashboard
from app.services import operational_alerts, system_status


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), ConnectionResetError(), gizmo.GizmoHTTPError("users", 503), gizmo.GizmoHTTPError("users", 429)],
)
def test_get_retries_transient_failure_with_same_request(monkeypatch, failure):
    client = gizmo.GizmoClient.__new__(gizmo.GizmoClient)
    calls, sleeps = [], []

    def once(resource, params):
        calls.append((resource, dict(params)))
        if len(calls) < 3:
            raise failure
        return {"data": [1]}

    monkeypatch.setattr(client, "_get_once", once)
    monkeypatch.setattr(gizmo.time, "sleep", sleeps.append)
    assert client.get("users", {"Pagination.Cursor": "opaque"}) == {"data": [1]}
    assert len(calls) == 3 and calls[0] == calls[1] == calls[2]
    assert sleeps == [1, 2]


@pytest.mark.parametrize(
    "failure",
    [
        gizmo.GizmoHTTPError("users", 401),
        gizmo.GizmoHTTPError("users", 403),
        gizmo.GizmoHTTPError("users/10", 404),
        ssl.SSLCertVerificationError("Untrusted"),
        gizmo.GizmoError("Invalid data"),
    ],
)
def test_invalid_credentials_tls_or_data_are_not_retried(monkeypatch, failure):
    client = gizmo.GizmoClient.__new__(gizmo.GizmoClient)
    calls = []

    def once(*args):
        calls.append(1)
        raise failure

    monkeypatch.setattr(client, "_get_once", once)
    monkeypatch.setattr(gizmo.time, "sleep", lambda _: pytest.fail("Should not retry"))
    with pytest.raises(type(failure)):
        client.get("users")
    assert calls == [1]


def test_exhausted_retry_raises_without_unbounded_wait(monkeypatch):
    client = gizmo.GizmoClient.__new__(gizmo.GizmoClient)
    calls, sleeps = [], []

    def once(*args):
        calls.append(1)
        raise TimeoutError()

    monkeypatch.setattr(client, "_get_once", once)
    monkeypatch.setattr(gizmo.time, "sleep", sleeps.append)
    with pytest.raises(TimeoutError):
        client.get("users")
    assert len(calls) == 3 and sleeps == [1, 2]


@pytest.mark.parametrize(
    "state,elapsed,due",
    [
        ("complete", 1799, False),
        ("complete", 1800, True),
        ("error", 299, False),
        ("error", 300, True),
        ("running", 0, True),
        ("complete", -300, True),
    ],
)
def test_per_club_cadence_and_crash_resume(state, elapsed, due):
    now = datetime(2026, 10, 6, 17, tzinfo=UTC)
    stamp = (now - timedelta(seconds=elapsed)).isoformat()
    assert sync.sync_is_due({"status": state, "finished_at_utc": stamp}, now) is due
    assert sync.sync_is_due({}, now)


def test_scheduler_isolates_failures_and_skips_unconfigured_club(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "require_stage_environment", lambda: None)
    monkeypatch.setattr(scheduler, "configured_clubs", lambda _: [1, 2, 3, 4])
    connections = []

    class Connection:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def connect():
        c = Connection()
        connections.append(c)
        return c

    monkeypatch.setattr(scheduler, "get_db_connection", connect)
    for club_id in (1, 2, 3):
        sync.atomic_json(tmp_path / f"sync-{club_id}.json", {"enabled": True})
    called = []

    def run(conn, club_id, *, directory, only_if_due):
        assert directory == tmp_path and only_if_due is True
        called.append(club_id)
        if club_id == 1:
            raise RuntimeError("private-key")
        return {"status": "paused" if club_id == 2 else "complete"}

    monkeypatch.setattr(scheduler, "synchronize", run)
    result = scheduler.synchronize_due(directory=tmp_path)
    assert called == [1, 2, 3]
    assert [r["status"] for r in result] == ["error", "paused", "complete"]
    assert "private-key" not in json.dumps(result)
    assert all(c.closed for c in connections)
    assert len(connections) == 4


def test_scheduler_checks_environment_before_connecting(tmp_path, monkeypatch):
    def reject():
        raise ValueError("not stage")

    monkeypatch.setattr(scheduler, "require_stage_environment", reject)
    monkeypatch.setattr(scheduler, "get_db_connection", lambda: pytest.fail("DB touched"))
    with pytest.raises(ValueError, match="not stage"):
        scheduler.synchronize_due(directory=tmp_path)
    assert not list(tmp_path.iterdir())


def test_scheduler_uses_only_explicit_disabled_gizmo_previews():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql):
            assert "c.integration_provider = 'gizmo'" in sql
            assert "c.service_enabled = 0 AND c.integration_ready = 0" in sql
            assert "JOIN club_integrations" in sql

        def fetchall(self):
            return [{"club_id": "42"}]

    class Connection:
        def cursor(self):
            return Cursor()

        def rollback(self):
            pass

    assert scheduler.configured_clubs(Connection()) == [42]


def test_admin_health_checks_only_jobs_for_each_provider(monkeypatch):
    now = datetime.now(UTC).replace(tzinfo=None)
    success = {"status": "success", "started_at": now}
    monkeypatch.setattr(
        dashboard,
        "get_latest_job_runs_by_club",
        lambda _: {
            1: {GIZMO_SYNC_JOB: success},
            2: {key: success for key in LANGAME_SYNC_JOBS},
        },
    )
    health = dashboard.get_club_sync_health(
        [
            {"club_id": 1, "integration_provider": "gizmo"},
            {"club_id": 2, "integration_provider": "langame"},
        ]
    )
    assert [r["overall"] for r in health] == ["success", "success"]
    assert [len(r["jobs"]) for r in health] == [1, 4]


def test_alerts_do_not_demand_langame_jobs_for_gizmo():
    now = datetime(2026, 10, 6, 17)
    kwargs = dict(clubs=[{"club_id": 1, "integration_provider": "gizmo"}], problem_jobs=[], stuck_mailings=[], now=now)
    assert (
        operational_alerts.build_operational_alerts(
            latest_jobs_by_club={1: {GIZMO_SYNC_JOB: {"status": "success", "started_at": now}}}, **kwargs
        )
        == []
    )
    alerts = operational_alerts.build_operational_alerts(latest_jobs_by_club={}, **kwargs)
    assert len(alerts) == 1 and alerts[0]["job_type"] == GIZMO_SYNC_JOB
    kwargs["clubs"][0]["service_enabled"] = 0
    assert operational_alerts.build_operational_alerts(latest_jobs_by_club={}, **kwargs) == []


def test_owner_gizmo_status_has_no_global_logfile_fallback(monkeypatch):
    monkeypatch.setattr(system_status, "_file_mtime_local", lambda *a: pytest.fail("Other club's log consulted"))
    tasks = system_status.update_tasks_for({"integration_provider": "gizmo"})
    assert len(tasks) == 1
    assert system_status._build_update_status(tasks[0], {})["status"] == "нет данных"
    assert system_status.update_tasks_for({}) == system_status.UPDATE_TASKS


def test_owner_gizmo_status_shows_in_progress(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda _: 1)
    result = system_status._build_update_status(
        system_status.GIZMO_UPDATE_TASK, {GIZMO_SYNC_JOB: {"status": "running", "started_at": datetime(2026, 10, 6)}}
    )
    assert result["status"] == "обновляется"
