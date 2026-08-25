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


class _CreateMissionCursor:
    def __init__(self):
        self.queries = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append(query)
        self.params.append(params)

    def fetchone(self):
        return {"next_id": 6}


class _CreateMissionConnection:
    def __init__(self):
        self.cursor_obj = _CreateMissionCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class _CountCursor:
    def __init__(self, count):
        self.count = count
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return {"cnt": self.count}


class _CountConnection:
    def __init__(self, count):
        self.cursor_obj = _CountCursor(count)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_create_club_mission_uses_next_free_global_id(monkeypatch):
    conn = _CreateMissionConnection()
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)
    monkeypatch.setattr(missions, "ensure_mission_reward_columns", lambda cursor: None)

    mission_id = missions.create_club_mission(
        club_id=1,
        mission_template_id=5,
        target_amount=3,
        custom_name="Новое задание",
    )

    insert_params = conn.cursor_obj.params[-1]
    next_id_query = conn.cursor_obj.queries[0]
    assert mission_id == 6
    assert insert_params[0] == 6
    assert insert_params[1] == 1
    assert insert_params[2] == 5
    assert "WHERE club_id" not in next_id_query
    assert conn.committed is True
    assert conn.closed is True


def test_mission_activity_uses_club_local_time(monkeypatch):
    seen = []

    def fake_local_now(timezone_name):
        seen.append(timezone_name)
        return datetime(2026, 8, 25, 11, 59)

    monkeypatch.setattr(missions, "get_club_local_now", fake_local_now)
    mission = {
        "club_timezone": "Asia/Yekaterinburg",
        "start_at": datetime(2026, 8, 25, 12, 0),
        "end_at": None,
    }

    assert missions.is_mission_active(mission) is False
    assert seen == ["Asia/Yekaterinburg"]
    assert missions.is_mission_active(mission, now=datetime(2026, 8, 25, 12, 0)) is True


def test_utc_event_period_uses_club_timezone():
    conditions, params = missions.build_period_filter(
        {
            "club_timezone": "Asia/Yekaterinburg",
            "start_at": datetime(2026, 8, 25, 12, 0),
            "end_at": datetime(2026, 8, 25, 18, 0),
        },
        date_field="created_at",
        timestamps_are_utc=True,
    )

    assert conditions == ["created_at >= %s", "created_at <= %s"]
    assert params == [datetime(2026, 8, 25, 7, 0), datetime(2026, 8, 25, 13, 0)]


def test_case_openings_mission_counts_all_cases(monkeypatch):
    conn = _CountConnection(4)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "case_openings_count",
            "target_amount": 3,
            "start_at": None,
            "end_at": None,
            "config": {},
        },
    )

    assert progress == 4
    assert "guest_case_openings" in conn.cursor_obj.query
    assert "case_id = %s" not in conn.cursor_obj.query
    assert conn.cursor_obj.params == [10, 1]
    assert conn.closed is True


def test_specific_case_openings_mission_filters_case(monkeypatch):
    conn = _CountConnection(2)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "specific_case_openings_count",
            "target_amount": 2,
            "start_at": None,
            "end_at": None,
            "config": {"case_id": 55},
        },
    )

    assert progress == 2
    assert "guest_case_openings" in conn.cursor_obj.query
    assert "case_id = %s" in conn.cursor_obj.query
    assert conn.cursor_obj.params == [10, 1, 55]
    assert conn.closed is True


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


def test_sessions_started_in_time_range_count_raw_session_starts(monkeypatch):
    rows = [
        {"date_start": datetime(2026, 8, 1, 17, 59), "date_stop": datetime(2026, 8, 1, 18, 30)},
        {"date_start": datetime(2026, 8, 1, 18, 0), "date_stop": datetime(2026, 8, 1, 19, 0)},
        {"date_start": datetime(2026, 8, 2, 20, 15), "date_stop": datetime(2026, 8, 2, 21, 0)},
        {"date_start": datetime(2026, 8, 3, 23, 0), "date_stop": datetime(2026, 8, 3, 23, 30)},
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "sessions_started_in_time_range_count",
            "target_amount": 2,
            "start_at": None,
            "end_at": None,
            "config": {"time_start": "18:00", "time_end": "23:00"},
        },
    )

    assert progress == 2
    assert conn.closed is True


def test_sessions_started_in_time_range_supports_overnight_window(monkeypatch):
    rows = [
        {"date_start": datetime(2026, 8, 1, 21, 59), "date_stop": datetime(2026, 8, 1, 22, 30)},
        {"date_start": datetime(2026, 8, 1, 22, 0), "date_stop": datetime(2026, 8, 1, 23, 0)},
        {"date_start": datetime(2026, 8, 2, 5, 59), "date_stop": datetime(2026, 8, 2, 6, 30)},
        {"date_start": datetime(2026, 8, 2, 6, 0), "date_stop": datetime(2026, 8, 2, 7, 0)},
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "sessions_started_in_time_range_count",
            "target_amount": 2,
            "start_at": None,
            "end_at": None,
            "config": {"time_start": "22:00", "time_end": "06:00"},
        },
    )

    assert progress == 2
    assert conn.closed is True


def test_session_hours_in_time_range_sums_started_sessions(monkeypatch):
    rows = [
        {"date_start": datetime(2026, 8, 1, 17, 59), "date_stop": datetime(2026, 8, 1, 20, 0)},
        {"date_start": datetime(2026, 8, 1, 18, 0), "date_stop": datetime(2026, 8, 1, 20, 30)},
        {"date_start": datetime(2026, 8, 2, 20, 15), "date_stop": datetime(2026, 8, 2, 22, 0)},
        {"date_start": datetime(2026, 8, 3, 23, 0), "date_stop": datetime(2026, 8, 4, 1, 0)},
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "session_hours_in_time_range_total",
            "target_amount": 4,
            "start_at": None,
            "end_at": None,
            "config": {"time_start": "18:00", "time_end": "23:00"},
        },
    )

    assert progress == 4
    assert conn.closed is True


def test_session_hours_in_time_range_supports_overnight_window(monkeypatch):
    rows = [
        {"date_start": datetime(2026, 8, 1, 21, 59), "date_stop": datetime(2026, 8, 1, 23, 0)},
        {"date_start": datetime(2026, 8, 1, 22, 0), "date_stop": datetime(2026, 8, 2, 0, 30)},
        {"date_start": datetime(2026, 8, 2, 5, 30), "date_stop": datetime(2026, 8, 2, 7, 0)},
        {"date_start": datetime(2026, 8, 2, 6, 0), "date_stop": datetime(2026, 8, 2, 8, 0)},
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(missions, "get_db_connection", lambda: conn)

    progress = missions.calculate_mission_progress(
        guest_id=10,
        club_id=1,
        mission={
            "target_metric": "session_hours_in_time_range_total",
            "target_amount": 4,
            "start_at": None,
            "end_at": None,
            "config": {"time_start": "22:00", "time_end": "06:00"},
        },
    )

    assert progress == 4
    assert conn.closed is True


def test_build_mission_config_reads_time_range():
    config = missions.build_mission_config_from_form(
        template={
            "target_metric": "sessions_started_in_time_range_count",
            "config_schema": {
                "time_start": {"label": "Начало интервала"},
                "time_end": {"label": "Конец интервала"},
            },
        },
        form={"time_start": "18:00", "time_end": "23:00"},
    )

    assert config == {"time_start": "18:00", "time_end": "23:00"}
