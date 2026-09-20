from datetime import date, timedelta
from importlib import import_module

import pytest
from flask import session

from app.main import app
from app.routes.owner.crm import _parse_heatmap_range


crm_route = import_module("app.routes.owner.crm")


def test_heatmap_range_accepts_custom_dates():
    date_from, date_to, current_start, current_end = _parse_heatmap_range(
        {"date_from": "2026-09-01", "date_to": "2026-09-20"}
    )

    assert date_from.isoformat() == "2026-09-01"
    assert date_to.isoformat() == "2026-09-20"
    assert current_start.isoformat() == "2026-09-01T00:00:00"
    assert current_end.isoformat() == "2026-09-21T00:00:00"


def test_heatmap_range_defaults_to_current_month():
    date_from, date_to, _, _ = _parse_heatmap_range({})

    assert date_from == date.today().replace(day=1)
    assert date_to == date.today()


@pytest.mark.parametrize(
    "args",
    [
        {"date_from": "2026-09-01"},
        {"date_from": "2026-09-20", "date_to": "2026-09-01"},
        {
            "date_from": (date.today() - timedelta(days=366)).isoformat(),
            "date_to": date.today().isoformat(),
        },
    ],
)
def test_heatmap_range_rejects_invalid_ranges(args):
    with pytest.raises(ValueError):
        _parse_heatmap_range(args)


def test_heatmap_page_applies_custom_range_to_both_maps(monkeypatch):
    calls = []

    def pc_stats(club_id, period_days, **kwargs):
        calls.append(("pc", club_id, period_days, kwargs))
        return {"pcs": []}

    def visit_stats(club_id, period_days, **kwargs):
        calls.append(("visits", club_id, period_days, kwargs))
        return {}

    monkeypatch.setattr(crm_route, "get_pc_hours_heatmap_stats", pc_stats)
    monkeypatch.setattr(crm_route, "get_visit_heatmap_stats", visit_stats)
    monkeypatch.setattr(crm_route, "render_template", lambda template, **context: context)

    with app.test_request_context(
        "/owner/analytics/heatmaps?date_from=2026-09-01&date_to=2026-09-20"
    ):
        session.update(user_id=1, role="owner", club_id=7)
        context = crm_route.analytics_heatmaps()

    assert context["selected_period"] == 20
    assert context["selected_date_from"] == "2026-09-01"
    assert context["selected_date_to"] == "2026-09-20"
    assert [call[:3] for call in calls] == [("pc", 7, 20), ("visits", 7, 20)]
    assert calls[0][3]["current_start"].isoformat() == "2026-09-01T00:00:00"
    assert calls[1][3]["current_end"].isoformat() == "2026-09-21T00:00:00"
