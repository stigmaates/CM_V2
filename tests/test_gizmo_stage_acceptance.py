"""Rehearse the server acceptance runner through the real admin creation route."""

import json

import pytest

from app.integrations import gizmo_onboarding as onboarding
from app.routes.admin import clubs
from scripts import verify_gizmo_stage_lifecycle as runner
from tests.test_gizmo_lifecycle import imported as imported
from tests.test_gizmo_onboarding import certificate as certificate
from tests.test_gizmo_onboarding import setup as setup


@pytest.mark.parametrize("incremental", [False, True])
def test_acceptance_creates_isolated_club_then_leaves_it_disabled(imported, monkeypatch, incremental):
    conn, directory = imported
    for field in ("name", "timezone", "owner_id", "lg_api_key", "secret"):
        conn.db.execute(f"ALTER TABLE clubs ADD COLUMN {field} TEXT")
    conn.db.execute("UPDATE clubs SET name='Next',timezone='Asia/Yekaterinburg'")
    conn.commit()
    monkeypatch.setattr(type(conn), "__enter__", lambda self: self, raising=False)
    monkeypatch.setattr(type(conn), "__exit__", lambda *a: None, raising=False)
    monkeypatch.setattr(type(conn), "close", lambda *a: None, raising=False)
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "require_stage_environment", lambda: None)
    monkeypatch.setattr(clubs, "get_db_connection", lambda: conn)
    monkeypatch.setattr(clubs, "gizmo_available", lambda: True)
    monkeypatch.setattr(clubs, "_column_exists", lambda *a: True)
    monkeypatch.setattr(
        clubs,
        "initial_setup",
        lambda club_id, credentials: onboarding.initial_setup(club_id, credentials, directory=directory),
    )
    from app.integrations import gizmo_sync as sync

    certificate = sync.private_json(directory / "sync-900001.json")["certificate_pem"]
    monkeypatch.setattr(sync, "discover", lambda *a: dict(certificate_pem=certificate, trusted=False))
    runner.run(900001, directory=directory, incremental=incremental)
    prefix = "acceptance-incremental" if incremental else "acceptance"
    report = json.loads((directory / f"{prefix}-report-900001.json").read_text())
    if incremental:
        assert report["initial_mode"] == "full"
        assert report["active_mode"] == report["repeat_mode"] == "incremental"
        assert report["scheduler_waits"] is True
    assert report["status"] == "complete"
    assert report["test_club_id"] == 900002
    assert report["initial"] == report["active"]
    assert report["disabled_stops_sync"] and report["resume_enabled"]
    assert report["test_service_disabled"] and report["test_sync_paused"]
    assert report["source_flags_unchanged"]
    assert conn.records("clubs")[0]["integration_ready"] == 0
    assert conn.records("clubs")[1]["integration_ready"] == 1
    assert all(row["service_enabled"] == 0 for row in conn.records("clubs"))
    assert len(conn.records("guest_sessions")) == 2
    if incremental:
        from scripts import verify_gizmo_schedule as schedule_runner

        monkeypatch.setattr(schedule_runner, "DIRECTORY", directory)
        monkeypatch.setattr(schedule_runner, "get_db_connection", lambda: conn)
        monkeypatch.setattr(schedule_runner, "require_stage_environment", lambda: None)
        monkeypatch.setattr(schedule_runner, "GizmoClient", sync.GizmoClient)
        monkeypatch.setattr(schedule_runner, "rebuild_club_portrait", sync.rebuild_club_portrait)
        monkeypatch.setattr(schedule_runner, "refresh_club", sync.refresh_club)
        schedule_runner.run()
        schedule_report = json.loads((directory / "schedule-acceptance.json").read_text())
        assert schedule_report["status"] == "complete"
        assert [cycle["parts"] for cycle in schedule_report["cycles"]] == [
            ["sessions"],
            ["sessions", "topups"],
            ["guests"],
        ]
        assert not schedule_report["cycles"][0]["api_calls"].get("users")
        assert not schedule_report["cycles"][0]["api_calls"].get("deposittransactions")
    # Rerun reuses only the manifest's acceptance club, never creates duplicates.
    runner.run(900001, directory=directory, incremental=incremental)
    assert len(conn.records("clubs")) == 2
    assert len(conn.records("guest_sessions")) == 2
