import copy
import json
from datetime import datetime, timedelta

import pytest

from app.integrations.gizmo_import import save
from app.integrations.gizmo_incremental import collect_sync
from app.integrations.gizmo_schedule import components_due, read_references
from app.integrations.gizmo_sync import sync_is_due
from tests.test_gizmo_incremental import API, NOW, run
from tests.test_gizmo_lifecycle import imported as imported
from tests.test_gizmo_onboarding import certificate as certificate
from tests.test_gizmo_onboarding import setup as setup
from tests.test_gizmo_store import Connection


def prepared():
    api = API()
    data = run(api)
    conn = Connection()
    save(conn, 900001, data)
    api.calls.clear()
    return api, conn, data["scope"]


@pytest.mark.parametrize(
    "minute,expected",
    [
        (1, {"sessions"}),
        (2, {"sessions"}),
        (3, {"guests", "sessions", "topups"}),
        (9, {"guests", "sessions", "topups"}),
        (10, {"sessions"}),
        (30, {"guests", "sessions", "topups"}),
    ],
)
def test_utc_cron_slots_and_catch_up(minute, expected):
    stamps = {
        "guests": (NOW + timedelta(minutes=((minute - 1) // 3) * 3)).isoformat(),
        "sessions": (NOW + timedelta(minutes=minute - 1)).isoformat(),
        "topups": (NOW + timedelta(minutes=((minute - 1) // 3) * 3)).isoformat(),
    }
    assert (
        components_due({"sync_checkpoint": {"component_success_at": stamps}}, NOW + timedelta(minutes=minute))
        == expected
    )


def test_guest_updates_catch_up_after_missed_three_minute_slot():
    now = NOW + timedelta(minutes=4)
    stamps = {"guests": NOW.isoformat(), "sessions": now.isoformat(), "topups": now.isoformat()}
    assert components_due({"sync_checkpoint": {"component_success_at": stamps}}, now) == {"guests"}


def test_first_run_and_backwards_clock_recover_all_components():
    assert components_due({}, NOW) == {"guests", "sessions", "topups"}
    stamps = {part: (NOW + timedelta(hours=1)).isoformat() for part in ("guests", "sessions", "topups")}
    assert components_due({"sync_checkpoint": {"component_success_at": stamps}}, NOW) == set(stamps)


def test_session_minute_uses_references_without_reading_or_rewriting_other_resources():
    api, conn, settings = prepared()
    before = {table: conn.records(table) for table in ("guests", "club_pc_names", "guest_balance_topups")}
    api.add_session(1301)
    at = NOW + timedelta(minutes=1)
    data = collect_sync(
        api,
        settings=settings,
        end=at,
        components=components_due(settings, at),
        references=read_references(conn, 900001),
    )
    assert data["scope"]["updated_components"] == ["sessions"]
    assert data["guests"] == data["hosts"] == data["topups"] == []
    assert not {"users", "hosts", "deposittransactions"} & {resource for resource, _ in api.calls}
    save(conn, 900001, data)
    for table, rows in before.items():
        assert conn.records(table) == rows
    assert len(conn.records("guest_sessions")) == 1301
    assert data["scope"]["sync_checkpoint"]["topups_through"] == settings["sync_checkpoint"]["topups_through"]


def test_unknown_guest_and_host_are_resolved_before_ten_minute_directory_refresh():
    api, conn, settings = prepared()
    api.add_session(1301)
    api.rows["sessions"][-1]["userId"] = 11
    api.rows["usersessions"][-1].update(userId=11, hostId=6)
    original = api.get

    def get(resource, params=None):
        if resource == "users/11":
            row = copy.deepcopy(api.rows["users"][0])
            row["Model"]["Id"] = 11
            return row
        if resource == "hosts/6":
            return {"Type": 0, "Model": {"Id": 6, "Name": "PC6", "Number": 6}}
        return original(resource, params)

    api.get = get
    data = collect_sync(
        api,
        settings=settings,
        end=NOW + timedelta(minutes=1),
        components={"sessions"},
        references=read_references(conn, 900001),
    )
    assert [g["guest_id"] for g in data["guests"]] == [11]
    assert [h["uuid"] for h in data["hosts"]] == ["gizmo:6"]
    save(conn, 900001, data)
    assert conn.records("guest_sessions")[-1]["guest_id"] == 11


def test_topup_window_has_its_own_cursor_and_failure_rolls_back_all_cadences():
    api, conn, settings = prepared()
    references = read_references(conn, 900001)
    sessions = collect_sync(
        api, settings=settings, end=NOW + timedelta(minutes=2), components={"sessions"}, references=references
    )
    save(conn, 900001, sessions)
    before = conn.records("club_integrations")
    api.calls.clear()
    combined = collect_sync(
        api,
        settings=sessions["scope"],
        end=NOW + timedelta(minutes=3),
        components={"sessions", "topups"},
        references=references,
    )
    query = next(params for resource, params in api.calls if resource == "deposittransactions")
    assert datetime.fromisoformat(query["DateFrom"]) == NOW - timedelta(days=7)
    conn.fail = True
    with pytest.raises(RuntimeError):
        save(conn, 900001, combined)
    assert conn.records("club_integrations") == before
    stamps = json.loads(before[0]["settings"])["sync_checkpoint"]["component_success_at"]
    assert stamps["topups"] == NOW.isoformat()


def test_reference_refresh_does_not_discard_unread_pending_sessions():
    api, conn, settings = prepared()
    settings["sync_checkpoint"]["pending"] = {"1": 10}
    data = collect_sync(api, settings=settings, end=NOW + timedelta(minutes=10), components={"guests"})
    assert data["scope"]["sync_checkpoint"]["pending"] == {"1": 10}
    assert not {"sessions", "usersessions", "deposittransactions"} & {resource for resource, _ in api.calls}


def test_missing_sort_support_does_not_start_full_import_every_minute():
    previous = dict(status="complete", incremental_supported=False, finished_at_utc=NOW.isoformat())
    assert not sync_is_due(previous, NOW + timedelta(minutes=1))
    assert sync_is_due(previous, NOW + timedelta(minutes=30))


def test_regular_active_sync_uses_shared_projection_jobs(imported, monkeypatch):
    from app.integrations import gizmo_lifecycle as lifecycle
    from app.integrations import gizmo_sync as sync

    conn, directory = imported
    lifecycle.set_service(conn, 900001, True, directory=directory)
    monkeypatch.setattr(sync, "rebuild_club_portrait", lambda *a: pytest.fail("Duplicated common portrait job"))
    monkeypatch.setattr(sync, "refresh_club", lambda *a, **kw: pytest.fail("Duplicated common Pulse job"))
    result = sync.synchronize(conn, 900001, directory=directory, only_if_due=True)
    assert result["projection_schedule"] == "shared"
    assert result["portrait"]["status"] == result["pulse"]["status"] == "scheduled"
    lifecycle.set_service(conn, 900001, False, directory=directory)
    lifecycle.set_service(conn, 900001, True, directory=directory)
