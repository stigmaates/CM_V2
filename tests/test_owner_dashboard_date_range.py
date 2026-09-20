from datetime import date
from importlib import import_module
from pathlib import Path

import pytest
from flask import session

from app.main import app
from app.services.dashboard import _date_labels_for_period

dashboard_route = import_module("app.routes.owner.dashboard")


def test_default_dashboard_range_is_last_seven_calendar_days():
    date_from, date_to, current_start, current_end, period_days = dashboard_route._parse_dashboard_range({})

    assert date_to == date.today()
    assert (date_to - date_from).days == 6
    assert (current_end - current_start).days == 7
    assert period_days == 7


def test_dashboard_range_accepts_custom_dates():
    date_from, date_to, current_start, current_end, period_days = dashboard_route._parse_dashboard_range(
        {"date_from": "2026-08-03", "date_to": "2026-08-12"}
    )

    assert date_from.isoformat() == "2026-08-03"
    assert date_to.isoformat() == "2026-08-12"
    assert current_start.isoformat() == "2026-08-03T00:00:00"
    assert current_end.isoformat() == "2026-08-13T00:00:00"
    assert period_days == 10
    assert [item.isoformat() for item in _date_labels_for_period(current_start, current_end)] == [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
    ]


def test_dashboard_range_rejects_ranges_over_one_year():
    with pytest.raises(ValueError, match="Максимальный диапазон"):
        dashboard_route._parse_dashboard_range(
            {"date_from": "2025-01-01", "date_to": "2026-01-02"}
        )


def test_dashboard_does_not_eagerly_calculate_all_time_engagement(monkeypatch):
    engagement_calls = []

    monkeypatch.setattr(dashboard_route, "get_club_info", lambda club_id: {"club_id": club_id})
    monkeypatch.setattr(
        dashboard_route,
        "get_dashboard_stats",
        lambda club_id, **kwargs: {"period_days": kwargs["period_days"]},
    )
    monkeypatch.setattr(
        dashboard_route,
        "get_dashboard_engagement_stats",
        lambda club_id, **kwargs: engagement_calls.append(kwargs["all_time"]) or {},
    )
    monkeypatch.setattr(dashboard_route, "get_case_openings_chart", lambda club_id, **kwargs: {})
    monkeypatch.setattr(dashboard_route, "get_mission_completions_chart", lambda club_id, **kwargs: {})
    monkeypatch.setattr(dashboard_route, "get_first_visit_feedback_stats", lambda club_id, **kwargs: {})
    monkeypatch.setattr(dashboard_route, "render_template", lambda template, **context: context)

    with app.test_request_context("/owner/dashboard"):
        session["user_id"] = 1
        session["role"] = "owner"
        session["club_id"] = 7
        context = dashboard_route.dashboard()

    assert engagement_calls == [False]
    assert context["selected_period"] == 7
    assert context["engagement_all_time_data"] is None


def test_dashboard_template_uses_custom_date_inputs_and_lazy_all_time_endpoint():
    template = Path("app/templates/owner/dashboard.html").read_text(encoding="utf-8")

    assert "css/team.css" in template
    assert 'name="date_from"' in template
    assert 'name="date_to"' in template
    assert 'data-dashboard-preset="week"' in template
    assert 'data-dashboard-preset="month"' in template
    assert 'id="dashboardCalendarPopover"' in template
    assert 'id="dashboardCalendarApply"' in template
    assert "dashboardDateRangeForm.requestSubmit()" in template
    assert "event.composedPath()" in template
    assert "period=7" not in template
    assert "period=30" not in template
    assert "period=90" not in template
    assert "/owner/api/dashboard/engagement" in template
    assert "cyberBonusOwnerDashboardScroll" in template
    assert "sessionStorage.setItem" in template
    assert "window.scrollTo" in template
