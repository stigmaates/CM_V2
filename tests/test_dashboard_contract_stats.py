from datetime import datetime
from pathlib import Path

from app.services import dashboard


class ContractStatsCursor:
    def __init__(self):
        self.calls = 0
        self.result = None
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls += 1
        self.queries.append((sql, params))
        if self.calls == 1:
            self.result = [
                {
                    "game": "dota2",
                    "difficulty": "hard",
                    "selected_count": 4,
                    "unique_guests_count": 3,
                    "completed_count": 1,
                },
                {
                    "game": "cs2",
                    "difficulty": "easy",
                    "selected_count": 6,
                    "unique_guests_count": 5,
                    "completed_count": 3,
                },
            ]
        else:
            self.result = {"unique_guests": 7}

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result


class ContractStatsConnection:
    def __init__(self):
        self.cursor_instance = ContractStatsCursor()

    def cursor(self):
        return self.cursor_instance

    def close(self):
        pass


def test_contract_stats_group_selected_cohort_by_game_and_difficulty(monkeypatch):
    connection = ContractStatsConnection()
    monkeypatch.setattr(dashboard, "get_db_connection", lambda: connection)

    stats = dashboard.get_contract_stats(
        1,
        current_start=datetime(2026, 9, 1),
        current_end=datetime(2026, 10, 1),
    )

    assert stats == {
        "items": [
            {
                "game": "cs2",
                "game_label": "CS2",
                "difficulty": "easy",
                "difficulty_label": "Лёгкие",
                "selected": 6,
                "unique_guests": 5,
                "completed": 3,
                "completion_percent": 50.0,
            },
            {
                "game": "dota2",
                "game_label": "Dota 2",
                "difficulty": "hard",
                "difficulty_label": "Сложные",
                "selected": 4,
                "unique_guests": 3,
                "completed": 1,
                "completion_percent": 25.0,
            },
        ],
        "total_selected": 10,
        "unique_guests": 7,
        "total_completed": 4,
        "period_days": 30,
    }
    first_query, first_params = connection.cursor_instance.queries[0]
    assert "started_at >= %s" in first_query
    assert "status IN (%s, %s, %s)" in first_query
    assert first_params[-3:] == ("active", "completed", "expired")


def test_owner_dashboard_contains_contract_analytics():
    template = Path("app/templates/owner/dashboard.html").read_text(encoding="utf-8")

    assert 'data-engagement-tab="contracts"' in template
    assert 'id="contractStatsPanel"' in template
    assert "Контрактов взяли" in template
    assert "Уникальных гостей" in template or "уникальных гостей" in template
    assert "Контрактов выполнили" in template or "контрактов выполнили" in template
