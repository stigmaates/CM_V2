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
