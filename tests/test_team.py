from datetime import date, datetime, timedelta

import httpx
import pytest

from app.services.team import build_report, date_range, shift_owner
from scripts.sync_team import fetch_team

D = datetime(2026, 1, 1, 10)


def shift(admin=1, start=D, stop=None):
    return dict(admin_id=admin, started_at=start, stopped_at=stop)


def report(guests, registrations=(), sessions=(), shifts=None):
    return build_report(
        [dict(admin_id=1, name="Админ 1")],
        shifts or [shift()],
        guests,
        registrations,
        sessions,
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
        datetime(2026, 4, 1),
    )


def test_shift_edges_gaps_and_overlaps():
    shifts = [shift(1, D, D + timedelta(hours=12)), shift(2, D + timedelta(hours=12))]
    assert shift_owner(D, shifts) == 1
    assert shift_owner(D + timedelta(hours=12), shifts) == 2
    assert shift_owner(D - timedelta(seconds=1), shifts) is None
    assert shift_owner(D, [shift(), shift()]) is None
    assert shift_owner(None, shifts) is None


def test_funnel_counts_visits_outside_registration_period_and_merges_extensions():
    sessions = [
        dict(guest_id=1, date_start=D, date_stop=D + timedelta(hours=1)),
        dict(guest_id=1, date_start=D + timedelta(hours=1), date_stop=D + timedelta(hours=2)),
        dict(guest_id=1, date_start=datetime(2026, 2, 2), date_stop=datetime(2026, 2, 2, 2)),
        dict(guest_id=1, date_start=datetime(2026, 3, 2), date_stop=datetime(2026, 3, 2, 2)),
        dict(guest_id=2, date_start=datetime(2026, 2, 3), date_stop=datetime(2026, 2, 3, 2)),
    ]
    result = report(
        [dict(guest_id=1, date_insert=D), dict(guest_id=2, date_insert=datetime(2026, 2, 1))], sessions=sessions
    )
    row = result["admins"][0]
    assert (row["cohort"], row["visit1"], row["visit2"], row["visit3"]) == (1, 1, 1, 1)
    assert row["conversion12"] == row["conversion23"] == 100


def test_module_attribution_uses_module_date_not_club_registration_date():
    shifts = [shift(1, D, D + timedelta(days=1)), shift(2, D + timedelta(days=1))]
    result = report(
        [dict(guest_id=1, date_insert=D)],
        [dict(guest_id=1, registered_at=D + timedelta(days=2), is_estimated=1)],
        shifts=shifts,
    )
    byid = {r["admin_id"]: r for r in result["admins"]}
    assert byid[1]["club_registrations"] == 1 and byid[1]["module_registrations"] == 0
    assert byid[2]["module_registrations"] == byid[2]["module_estimated"] == 1


def test_unknown_dates_and_unassigned_are_not_silently_attributed():
    result = report(
        [dict(guest_id=1, date_insert=D - timedelta(hours=1)), dict(guest_id=2, date_insert=None)],
        [dict(guest_id=2, registered_at=None, is_estimated=1)],
    )
    assert result["unknown_club_dates"] == result["unknown_module_dates"] == 1
    assert result["admins"][-1]["club_registrations"] == 1
    assert result["admins"][0]["conversion12"] is None


def test_unfinished_and_future_sessions_do_not_count():
    result = report(
        [dict(guest_id=1, date_insert=D)],
        sessions=[
            dict(guest_id=1, date_start=D, date_stop=None),
            dict(guest_id=1, date_start=datetime(2027, 1, 1), date_stop=datetime(2027, 1, 1, 2)),
        ],
    )
    assert result["admins"][0]["cohort"] == 1 and result["admins"][0]["visit1"] == 0


def test_ranges_inclusive_and_invalid_dates():
    assert date_range("2026-01-01", "2026-01-31", date(2026, 2, 1)) == (date(2026, 1, 1), date(2026, 1, 31))
    for first, last in [("2026-02-02", "2026-02-01"), ("2026-01-01", "2027-01-01"), ("bad", "2026-01-01")]:
        with pytest.raises(ValueError):
            date_range(first, last, date(2026, 2, 1))


def test_langame_pagination_club_scope_and_former_staff():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("clubs/list"):
            data = [dict(id=99, club_secret="demo"), dict(id=100, club_secret="other")]
        elif request.url.path.endswith("users/list"):
            data = [dict(id=1, work_point="99"), dict(id=2, work_point="100"), dict(id=3, work_point="100")]
        else:
            page = int(request.url.params["page"])
            return httpx.Response(
                200,
                json=dict(
                    status=True, data=[dict(id=page, list_clubs_id=99 if page == 2 else 100, user_id=2)], total_pages=2
                ),
            )
        return httpx.Response(200, json=dict(status=True, data=data))

    with httpx.Client(base_url="https://demo.test/", transport=httpx.MockTransport(handler)) as client:
        cid, admins, shifts = fetch_team(client, "demo")
    assert cid == 99 and [a["id"] for a in admins] == [1, 2]
    assert len(shifts) == 1 and shifts[0]["id"] == 2
    assert len(requests) == 4 and all(r.method == "GET" for r in requests)


def test_ambiguous_club_mapping_is_rejected():
    with httpx.Client(
        base_url="https://demo.test/",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=dict(status=True, data=[dict(id=1), dict(id=2)]))
        ),
    ) as client:
        with pytest.raises(ValueError, match="mapping_required"):
            fetch_team(client, "demo")


def test_team_endpoint_owner_club_scope(monkeypatch):
    import app.core as core
    from app.main import app
    from app.routes.owner import team

    monkeypatch.setattr(core, "is_club_service_enabled", lambda cid: True)

    class Conn:
        def close(self):
            pass

    monkeypatch.setattr(team, "get_db_connection", Conn)
    calls = []

    def load(conn, cid, args):
        calls.append(cid)
        return {"admins": []}

    monkeypatch.setattr(team, "load_report", load)
    client = app.test_client()
    assert client.get("/owner/api/team").status_code == 302
    with client.session_transaction() as sess:
        sess.update(user_id=1, role="owner", club_id=7, club_name="Test")
    assert client.get("/owner/team").status_code == 200
    assert client.get("/owner/api/team?club_id=99").status_code == 200
    assert calls == [7]


def test_club_local_dates_and_cohort_sql_boundaries(monkeypatch):
    from app.services import team

    calls = []

    def query(conn, sql, args=()):
        calls.append((sql, args))
        if "SELECT timezone" in sql:
            return [{"timezone": "Asia/Yekaterinburg"}]
        if "FROM team_admins" in sql:
            return [dict(admin_id=1, name="Admin")]
        if "FROM team_shifts" in sql:
            return [shift(1, datetime(2025, 12, 31, 19), datetime(2026, 1, 1, 19))]
        if "FROM guests WHERE" in sql:
            return [dict(guest_id=1, date_insert=datetime(2025, 12, 31, 20))]
        if "FROM module_registrations" in sql:
            return [dict(guest_id=1, registered_at=datetime(2025, 12, 31, 21), is_estimated=0)]
        return []

    monkeypatch.setattr(team, "rows", query)
    result = team.load_report(
        object(),
        7,
        {
            "registration_from": "2026-01-01",
            "registration_to": "2026-01-01",
            "cohort_from": "2026-01-01",
            "cohort_to": "2026-01-01",
        },
    )
    assert result["admins"][0]["club_registrations"] == result["admins"][0]["module_registrations"] == 1
    params = next(args for sql, args in calls if "FROM guest_sessions s" in sql)
    assert params[:3] == (7, datetime(2025, 12, 31, 19), datetime(2026, 1, 1, 19))


def test_team_tables_survive_business_mirror():
    from scripts.mirror_production_to_stage import PRESERVE

    assert {"module_registrations", "team_admins", "team_shifts", "team_sync_state"} <= PRESERVE
