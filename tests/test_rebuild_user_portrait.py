from datetime import datetime

from scripts.rebuild_user_portrait import collapse_sessions_to_visits


def test_sessions_are_collapsed_into_visits_by_two_hour_gap():
    rows = [
        {"date_start": datetime(2026, 7, 1, 10, 0), "date_stop": datetime(2026, 7, 1, 11, 0)},
        {"date_start": datetime(2026, 7, 1, 11, 30), "date_stop": datetime(2026, 7, 1, 12, 0)},
        {"date_start": datetime(2026, 7, 1, 15, 30), "date_stop": datetime(2026, 7, 1, 16, 0)},
    ]

    visits = collapse_sessions_to_visits(rows)

    assert len(visits) == 2
    assert visits[0]["date_start"] == datetime(2026, 7, 1, 10, 0)
    assert visits[0]["date_stop"] == datetime(2026, 7, 1, 12, 0)
    assert visits[1]["date_start"] == datetime(2026, 7, 1, 15, 30)
