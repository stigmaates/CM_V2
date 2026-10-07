"""Compare incremental imports with full snapshots, including real DB rollback."""

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_gizmo_integration import deposit, member
from test_gizmo_store import Connection

from app.integrations.gizmo import GizmoHTTPError
from app.integrations.gizmo_import import save
from app.integrations.gizmo_incremental import UnsupportedQuery, collect_sync, ordered_tail

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
SETTINGS = {"branch_id": 1, "cash_method_ids": [-1]}


class API:
    def __init__(self):
        self.rows = {
            "branches": [{"id": 1}],
            "paymentmethods": [{"id": -1}],
            "users": [member()],
            "hosts": [{"Type": 0, "Model": {"Id": 5, "Name": "PC05", "Number": 5}}],
            "deposittransactions": [deposit(), deposit(id=51, date="2026-09-01T10:00:00Z")],
            "sessions": [],
            "usersessions": [],
        }
        self.calls = []
        self.delivered = {}
        self.ignore = None
        self.failure = None
        for identity in range(1, 1301):
            self.add_session(identity)

    def add_session(self, identity, *, opened=False, start="2026-10-01T10:00:00Z"):
        self.rows["sessions"].append(
            dict(id=identity, userId=10, span=3500, startTime=start, endTime=None if opened else "2026-10-01T11:00:00Z")
        )
        self.rows["usersessions"].append(dict(id=identity, userId=10, hostId=5, state=1 if opened else 2, span=3500))

    def get(self, resource, params=None):
        params = dict(params or {})
        self.calls.append((resource, params))
        if self.failure and "Pagination.SortBy" in params:
            raise self.failure
        if resource.startswith("usersessions/"):
            return copy.deepcopy(next(r for r in self.rows["usersessions"] if r["id"] == int(resource.split("/")[1])))
        rows = list(self.rows[resource])
        if "UserId" in params and self.ignore != "user":
            rows = [r for r in rows if r["userId"] == params["UserId"]]
        if "DateFrom" in params and self.ignore != "date":
            lo = datetime.fromisoformat(params["DateFrom"])
            hi = datetime.fromisoformat(params["DateTo"])
            rows = [r for r in rows if lo <= datetime.fromisoformat(r["date"].replace("Z", "+00:00")) <= hi]
        if "Pagination.SortBy" in params and self.ignore != resource:
            rows.sort(key=lambda r: r["id"], reverse=params["Pagination.IsAsc"] == "false")
        offset = int(params.get("Pagination.Cursor", "0"))
        limit = int(params.get("Pagination.Limit", 500))
        page = rows[offset : offset + limit]
        self.delivered[resource] = self.delivered.get(resource, 0) + len(page)
        return {"data": copy.deepcopy(page), "nextCursor": str(offset + limit) if offset + limit < len(rows) else None}


def run(api, settings=SETTINGS, after=0, **kwargs):
    return collect_sync(api, settings=settings, end=NOW + timedelta(hours=after), **kwargs)


def test_regular_import_matches_full_snapshot_without_reloading_history():
    api = API()
    first = run(api)
    conn = Connection()
    save(conn, 900001, first)
    api.add_session(1301)
    api.rows["deposittransactions"][0]["isVoided"] = True
    api.delivered.clear()
    delta = run(api, first["scope"], after=1)
    assert delta["scope"]["sync_mode"] == "incremental"
    assert len(delta["sessions"]) == 201
    assert api.delivered["sessions"] == 500
    assert api.delivered["usersessions"] == 500
    assert api.delivered["deposittransactions"] == 1
    save(conn, 900001, delta)
    save(conn, 900001, delta)
    reference = Connection()
    save(reference, 900001, run(api, after=1))
    for table, key in (("guest_sessions", "id"), ("guest_balance_topups", "topup_id"), ("guests", "guest_id")):
        actual = sorted(conn.records(table), key=lambda r: r[key])
        expected = sorted(reference.records(table), key=lambda r: r[key])
        # Surrogate IDs and import bookkeeping are local, not source business data.
        for rows in (actual, expected):
            for row in rows:
                row.pop("updated_at", None)
                row.pop("created_at", None)
                if table == "guest_balance_topups":
                    row.pop("id", None)
        assert actual == expected


def test_old_open_session_is_revisited_after_it_falls_outside_overlap():
    api = API()
    api.rows["sessions"][0]["endTime"] = None
    api.rows["usersessions"][0]["state"] = 1
    first = run(api)
    assert first["scope"]["sync_checkpoint"]["pending"] == {"1": 10}
    api.rows["sessions"][0]["endTime"] = "2026-10-01T11:00:00Z"
    api.rows["usersessions"][0]["state"] = 2
    api.calls.clear()
    delta = run(api, first["scope"], after=1)
    assert 1 in {r["id"] for r in delta["sessions"]}
    assert delta["scope"]["sync_checkpoint"]["pending"] == {}
    assert any(resource == "sessions" and params.get("UserId") == 10 for resource, params in api.calls)
    assert ("usersessions/1", {}) in api.calls


def test_new_session_after_cutoff_is_kept_pending_for_next_run():
    api = API()
    api.add_session(1301, start="2026-10-07T12:05:00Z")
    api.rows["sessions"][-1]["endTime"] = "2026-10-07T12:10:00Z"
    first = run(api)
    assert first["scope"]["sync_checkpoint"]["pending"] == {"1301": 10}
    delta = run(api, first["scope"], after=1)
    assert 1301 in {r["id"] for r in delta["sessions"]}


def test_daily_reconciliation_catches_old_voids_and_session_corrections():
    api = API()
    first = run(api)
    api.rows["deposittransactions"][1]["isVoided"] = True
    api.rows["sessions"][1]["endTime"] = "2026-10-01T11:01:00Z"
    delta = run(api, first["scope"], after=1)
    assert 51 not in {r["topup_id"] for r in delta["topups"]}
    daily = run(api, delta["scope"], after=24)
    assert daily["scope"]["sync_mode"] == "full"
    assert next(r for r in daily["topups"] if r["topup_id"] == 51)["amount"] == 0
    assert next(r for r in daily["sessions"] if r["id"] == 2)["date_stop"].minute == 1


def test_failed_database_write_does_not_advance_checkpoint_or_leave_partial_data():
    api = API()
    first = run(api)
    conn = Connection()
    save(conn, 900001, first)
    before = conn.records("club_integrations")
    api.add_session(1301)
    delta = run(api, first["scope"], after=1)
    conn.fail = True
    with pytest.raises(RuntimeError, match="injected"):
        save(conn, 900001, delta)
    assert conn.records("club_integrations") == before
    assert len(conn.records("guest_sessions")) == 1300
    conn.fail = False
    retry = run(api, json.loads(before[0]["settings"]), after=2)
    save(conn, 900001, retry)
    assert len(conn.records("guest_sessions")) == 1301
    assert json.loads(conn.records("club_integrations")[0]["settings"])["sync_checkpoint"]["session_high_id"] == 1301


@pytest.mark.parametrize("ignored", ["sessions", "usersessions", "date"])
def test_ignored_filter_falls_back_to_complete_import(ignored):
    api = API()
    first = run(api)
    api.ignore = ignored
    delta = run(api, first["scope"], after=1)
    assert delta["scope"]["sync_mode"] == "full"
    assert delta["scope"]["sync_reason"] == "api_filter_fallback"
    assert len(delta["sessions"]) == 1300


@pytest.mark.parametrize("failure", [GizmoHTTPError("sessions", 401), TimeoutError("network")])
def test_auth_or_network_error_aborts_without_fallback(failure):
    api = API()
    first = run(api)
    api.failure = failure
    with pytest.raises(type(failure)):
        run(api, first["scope"], after=1)


@pytest.mark.parametrize("after,forced", [(-1, False), (1, True)])
def test_clock_change_or_explicit_refresh_reloads_full_history(after, forced):
    api = API()
    first = run(api)
    assert run(api, first["scope"], after=after, force_full=forced)["scope"]["sync_mode"] == "full"


def test_sort_order_is_checked_across_page_boundaries():
    class Broken:
        def get(self, resource, params):
            if "Pagination.Cursor" not in params:
                return {"data": [{"id": 900}, {"id": 800}], "nextCursor": "opaque"}
            return {"data": [{"id": 850}], "nextCursor": None}

    with pytest.raises(UnsupportedQuery):
        ordered_tail(Broken(), "sessions", 0, "id")
