from datetime import datetime
from importlib import import_module

import pytest
from flask import render_template, session

from app.main import app
from scripts import rebuild_user_portrait as portrait


class RowsConnection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        self.queries.append((sql, params))

    def fetchall(self):
        return self.rows


def test_ufa_night_weekend_and_recency_use_local_dates_but_persist_utc():
    start, stop = datetime(2026, 10, 2, 20), datetime(2026, 10, 2, 21)
    conn = RowsConnection(
        [dict(club_id=9, guest_id=42, date_start=start, date_stop=stop, club_timezone="Asia/Yekaterinburg")]
    )
    result = portrait.fetch_sessions_agg(conn, datetime(2026, 10, 3, 1), club_id=9)[9, 42]
    assert result["favorite_period"] == "night"
    assert result["night_share"] == result["weekend_share"] == 1
    assert result["days_since_last_visit"] == 0
    assert result["first_visit_date"] == start
    assert result["last_visit_date"] == start
    assert result["total_hours_all"] == 1
    assert conn.queries[0][1] == (9, 9)


@pytest.mark.parametrize(
    "helper,args",
    [
        ("fetch_guests", ()),
        ("fetch_sessions_agg", (datetime(2026, 10, 6),)),
        ("fetch_topups_agg", (datetime(2026, 10, 6),)),
        ("fetch_spins_agg", ()),
        ("fetch_cases_agg", ()),
        ("fetch_missions_agg", (datetime(2026, 10, 6),)),
        ("fetch_steam_games_agg", ()),
    ],
)
def test_each_projection_source_has_a_bound_club_scope(helper, args):
    conn = RowsConnection([])
    getattr(portrait, helper)(conn, *args, club_id=900001)
    assert len(conn.queries) == 1
    sql, params = conn.queries[0]
    assert "club_id=%s" in sql
    assert params[-2:] == (900001, 900001)


def test_targeted_portrait_refresh_rejects_any_cross_club_write(monkeypatch):
    class Conn:
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    conn = Conn()
    monkeypatch.setattr(portrait, "build_records", lambda *a, **k: [dict(club_id=1)])
    monkeypatch.setattr(portrait, "upsert_user_portrait", lambda *a: pytest.fail("Cross-club write"))
    with pytest.raises(ValueError, match="scope"):
        portrait.rebuild_club_portrait(conn, 900001)
    assert conn.rolled_back


@pytest.mark.parametrize("provider,expected_updates", [("gizmo", 1), ("langame", 0)])
def test_only_langame_settings_require_langame_credentials(monkeypatch, provider, expected_updates):
    settings = import_module("app.routes.owner.settings")
    updates = []
    monkeypatch.setattr(settings, "get_club_info", lambda *a: dict(integration_provider=provider))
    monkeypatch.setattr(settings, "update_club_info", lambda *a, **k: updates.append((a, k)))
    monkeypatch.setattr(settings, "record_audit_event", lambda **k: None)
    with app.test_request_context(
        "/owner/settings", method="POST", data={"name": "Next", "timezone": "Asia/Yekaterinburg"}
    ):
        session.update(user_id=1, role="owner", club_id=900001)
        response = settings.settings()
    assert response.status_code == 302
    assert len(updates) == expected_updates
    if updates:
        assert updates[0][0][2:4] == ("", "")


def test_gizmo_owner_form_does_not_show_required_langame_secrets():
    with app.test_request_context("/owner/settings"):
        html = render_template(
            "owner/settings.html",
            active_tab="club",
            club=dict(name="Next", integration_provider="gizmo"),
            pc_name_settings=[],
            timezone_choices=[],
            system_status=dict(updates=[], auto_mailings=[]),
        )
    assert "Gizmo" in html
    assert 'name="lg_api_key"' not in html
    assert 'name="secret"' not in html
