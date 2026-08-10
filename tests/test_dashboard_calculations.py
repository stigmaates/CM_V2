from datetime import datetime

from app.services.dashboard import _has_later_collapsed_visit


def test_later_visit_ignores_same_collapsed_visit_extensions():
    sessions = [
        {"date_start": datetime(2026, 8, 1, 10, 0), "date_stop": datetime(2026, 8, 1, 11, 0)},
        {"date_start": datetime(2026, 8, 1, 11, 30), "date_stop": datetime(2026, 8, 1, 12, 0)},
    ]

    assert _has_later_collapsed_visit(sessions, datetime(2026, 8, 1, 10, 30)) is False


def test_later_visit_detects_next_collapsed_visit_after_event():
    sessions = [
        {"date_start": datetime(2026, 8, 1, 10, 0), "date_stop": datetime(2026, 8, 1, 11, 0)},
        {"date_start": datetime(2026, 8, 1, 11, 30), "date_stop": datetime(2026, 8, 1, 12, 0)},
        {"date_start": datetime(2026, 8, 1, 15, 0), "date_stop": datetime(2026, 8, 1, 16, 0)},
    ]

    assert _has_later_collapsed_visit(sessions, datetime(2026, 8, 1, 10, 30)) is True
