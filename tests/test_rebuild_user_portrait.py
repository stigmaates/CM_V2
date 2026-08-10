from datetime import datetime

from app.services.crm_segments import calculate_crm_segment
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


def test_crm_segment_requires_current_activity_for_top():
    segment = calculate_crm_segment(total_visits=30, visits_30d=1, visits_90d=18, days_since_last_visit=0)

    assert segment.crm_type == "rare"


def test_crm_segment_marks_top_by_30_day_activity():
    segment = calculate_crm_segment(total_visits=12, visits_30d=8, visits_90d=12, days_since_last_visit=0)

    assert segment.crm_type == "top"
    assert "8 визитов за 30 дней" in segment.reason


def test_crm_segment_keeps_recency_risk_above_historical_frequency():
    segment = calculate_crm_segment(total_visits=60, visits_30d=0, visits_90d=20, days_since_last_visit=35)

    assert segment.crm_type == "lost"
    assert segment.reason == "не был 35 дн."


def test_crm_segment_marks_base_by_moderate_current_activity():
    segment = calculate_crm_segment(total_visits=5, visits_30d=3, visits_90d=5, days_since_last_visit=1)

    assert segment.crm_type == "base"
