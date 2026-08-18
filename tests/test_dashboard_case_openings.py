from datetime import datetime

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


class PeriodFakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class PeriodFakeConnection:
    def __init__(self, rows):
        self.cursor_instance = PeriodFakeCursor(rows)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        pass


def test_case_openings_period_chart_groups_cases_and_fills_empty_periods(monkeypatch):
    rows = [
        {"period_start": datetime(2026, 7, 1), "case_id": 1, "case_name": "Alpha", "openings_count": 3},
        {"period_start": datetime(2026, 7, 1), "case_id": 2, "case_name": "Beta", "openings_count": 1},
        {"period_start": datetime(2026, 9, 1), "case_id": 2, "case_name": "Beta", "openings_count": 2},
        {"period_start": datetime(2026, 9, 1), "case_id": 3, "case_name": "Gamma", "openings_count": 5},
    ]
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: PeriodFakeConnection(rows))

    chart = dashboard.get_case_openings_period_chart(1, "month", top_cases=2)

    assert chart["labels"] == ["07.2026", "08.2026", "09.2026"]
    assert [item["name"] for item in chart["series"]] == ["Gamma", "Alpha", "Другие"]
    assert chart["series"][0]["values"] == [0, 0, 5]
    assert chart["series"][1]["values"] == [3, 0, 0]
    assert chart["series"][2]["values"] == [1, 0, 2]
    assert chart["max_value"] == 5


def test_wheel_spins_period_chart_fills_empty_weeks(monkeypatch):
    rows = [
        {"period_start": datetime(2026, 8, 3), "spins_count": 4},
        {"period_start": datetime(2026, 8, 17), "spins_count": 2},
    ]
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: PeriodFakeConnection(rows))

    chart = dashboard.get_wheel_spins_period_chart(1, "week")

    assert [item["label"] for item in chart["items"]] == ["03.08", "10.08", "17.08"]
    assert [item["count"] for item in chart["items"]] == [4, 0, 2]
    assert chart["total"] == 6
