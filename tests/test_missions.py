from datetime import datetime

from app.services import missions


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_min_hours_mission_counts_collapsed_visit_not_raw_sessions(monkeypatch):
    rows = [
        {"date_start": datetime(2026, 7, 25, 23, 33), "date_stop": datetime(2026, 7, 26, 0, 1)},
        {"date_start": datetime(2026, 7, 26, 0, 1), "date_stop": datetime(2026, 7, 26, 0, 24)},
        {"date_start": datetime(2026, 7, 26, 0, 24), "date_stop": datetime(2026, 7, 26, 0, 27)},
        {"date_start": datetime(2026, 7, 26, 0, 27), "date_stop": datetime(2026, 7, 26, 0, 53)},
        {"date_start": datetime(2026, 7, 26, 0, 53), "date_stop": datetime(2026, 7, 26, 1, 12)},
        {"date_start": datetime(2026, 7, 26, 1, 12), "date_stop": datetime(2026, 7, 26, 1, 24)},
        {"date_start": datetime(2026, 7, 26, 2, 32), "date_stop": datetime(2026, 7, 26, 3, 0)},
        {"date_start": datetime(2026, 7, 26, 3, 0), "date_stop": datetime(2026, 7, 26, 3, 18)},
        {"date_start": datetime(2026, 7, 26, 3, 18), "date_stop": datetime(2026, 7, 26, 3, 31)},
        {"date_start": datetime(2026, 7, 26, 3, 31), "date_stop": datetime(2026, 7, 26, 3, 47)},
        {"date_start": datetime(2026, 7, 26, 3, 47), "date_stop": datetime(2026, 7, 26, 3, 59)},
        {"date_start": datetime(2026, 7, 26, 3, 59), "date_stop": datetime(2026, 7, 26, 4, 19)},
        {"date_start": datetime(2026, 7, 26, 4, 19), "date_stop": datetime(2026, 7, 26, 4, 39)},
        {"date_start": datetime(2026, 7, 26, 4, 39), "date_stop": datetime(2026, 7, 26, 5, 0)},
        {"date_start": datetime(2026, 7, 26, 5, 0), "date_stop": datetime(2026, 7, 26, 5, 8)},
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=63301,
        club_id=1,
        mission={
            "target_metric": "visits_min_hours_count",
            "target_amount": 1,
            "start_at": None,
            "end_at": None,
            "config": {"min_hours": 3},
        },
    )

    assert progress == 1
    assert conn.closed is True
