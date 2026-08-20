from datetime import date
from pathlib import Path

from app.services import dashboard


class FakeCursor:
    def __init__(self):
        self.calls = 0
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls += 1
        if self.calls == 1:
            self.result = [
                {
                    "case_id": 10,
                    "case_name": "Cyber Case",
                    "case_image_url": "",
                    "sort_order": 1,
                    "openings_count": 4,
                    "unique_openers_count": 3,
                }
            ]
        elif self.calls == 2:
            self.result = {"unique_openers": 3}
        elif self.calls == 3:
            self.result = [
                {
                    "case_id": 10,
                    "item_id": 100,
                    "item_name": "25 КБ",
                    "rarity_label": "Обычный",
                    "probability": 70,
                    "drops_count": 3,
                },
                {
                    "case_id": 10,
                    "item_id": 101,
                    "item_name": "150 КБ",
                    "rarity_label": "Редкий",
                    "probability": 20,
                    "drops_count": 1,
                },
                {
                    "case_id": 10,
                    "item_id": 102,
                    "item_name": "500 КБ",
                    "rarity_label": "Ультра",
                    "probability": 10,
                    "drops_count": 0,
                },
            ]

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def close(self):
        pass


def test_case_openings_chart_includes_prize_drop_distribution(monkeypatch):
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: FakeConnection())

    chart = dashboard.get_case_openings_chart(1, 30)

    assert chart["total_openings"] == 4
    assert chart["unique_openers"] == 3
    assert chart["items"][0]["prize_drops"] == [
        {
            "item_id": 100,
            "name": "25 КБ",
            "rarity": "Обычный",
            "drops": 3,
            "percent": 75.0,
            "configured_percent": 70.0,
        },
        {
            "item_id": 101,
            "name": "150 КБ",
            "rarity": "Редкий",
            "drops": 1,
            "percent": 25.0,
            "configured_percent": 20.0,
        },
        {
            "item_id": 102,
            "name": "500 КБ",
            "rarity": "Ультра",
            "drops": 0,
            "percent": 0.0,
            "configured_percent": 10.0,
        },
    ]


class TimelineCursor:
    def __init__(self):
        self.calls = 0
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls += 1
        if self.calls == 1:
            self.result = [
                {"case_id": 10, "case_name": "Base Case", "sort_order": 1},
                {"case_id": 20, "case_name": "Pro Case", "sort_order": 2},
            ]
        else:
            self.result = [
                {"case_id": 10, "opening_date": date(2026, 8, 3), "openings_count": 2},
                {"case_id": 10, "opening_date": date(2026, 8, 5), "openings_count": 3},
                {"case_id": 20, "opening_date": date(2026, 8, 9), "openings_count": 4},
                {"case_id": 20, "opening_date": date(2026, 8, 10), "openings_count": 1},
            ]

    def fetchall(self):
        return self.result


class TimelineConnection:
    def cursor(self):
        return TimelineCursor()

    def close(self):
        pass


def test_case_openings_timeline_groups_by_calendar_week(monkeypatch):
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: TimelineConnection())

    timeline = dashboard.get_case_openings_timeline(
        1,
        date(2026, 8, 3),
        date(2026, 8, 12),
        "week",
    )

    assert [case["name"] for case in timeline["cases"]] == ["Base Case", "Pro Case"]
    assert timeline["buckets"] == [
        {"key": "2026-08-03", "label": "03–09.08", "values": [5, 4]},
        {"key": "2026-08-10", "label": "10–16.08", "values": [0, 1]},
    ]
    assert timeline["max_value"] == 5


def test_case_openings_timeline_keeps_empty_days(monkeypatch):
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: TimelineConnection())

    timeline = dashboard.get_case_openings_timeline(
        1,
        date(2026, 8, 3),
        date(2026, 8, 5),
        "day",
    )

    assert [bucket["label"] for bucket in timeline["buckets"]] == ["03.08", "04.08", "05.08"]
    assert timeline["buckets"][1]["values"] == [0, 0]


def test_owner_dashboard_contains_case_timeline_controls():
    template = Path("app/templates/owner/dashboard.html").read_text(encoding="utf-8")

    assert 'id="caseOpeningsTimeline"' in template
    assert 'data-case-period="custom"' in template
    assert 'data-case-group="month"' in template
    assert "/owner/api/dashboard/case-openings-timeline" in template


def test_case_openings_timeline_api_rejects_too_large_range():
    from flask import session

    from app.main import app
    from app.routes.owner.dashboard import case_openings_timeline

    with app.test_request_context(
        "/owner/api/dashboard/case-openings-timeline"
        "?period=custom&date_from=2025-01-01&date_to=2026-08-01&group_by=day"
    ):
        session["user_id"] = 1
        session["role"] = "owner"
        session["club_id"] = 1
        response, status = case_openings_timeline()

    assert status == 400
    assert response.get_json()["error"] == "Максимальный диапазон — 366 дней"
