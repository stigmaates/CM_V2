from datetime import datetime

from app.services.dashboard import _calculate_hourly_utilization
from app.services.pc_heatmap import _merged_occupied_seconds


def test_hourly_utilization_uses_occupied_time_and_pc_capacity():
    start = datetime(2026, 9, 7, 10, 0)
    end = datetime(2026, 9, 7, 12, 0)
    rows = [
        {
            "uuid": "pc-1",
            "date_start": datetime(2026, 9, 7, 10, 0),
            "date_stop": datetime(2026, 9, 7, 11, 0),
        },
        {
            "uuid": "pc-2",
            "date_start": datetime(2026, 9, 7, 10, 30),
            "date_stop": datetime(2026, 9, 7, 11, 30),
        },
    ]

    percentages, overall, sessions, pc_count = _calculate_hourly_utilization(rows, start, end, 2)

    assert percentages[(0, 10)] == 75
    assert percentages[(0, 11)] == 25
    assert overall == 50
    assert sessions == 2
    assert pc_count == 2


def test_hourly_utilization_does_not_double_count_overlapping_sessions_on_one_pc():
    start = datetime(2026, 9, 7, 10, 0)
    end = datetime(2026, 9, 7, 11, 0)
    rows = [
        {"uuid": "pc-1", "date_start": start, "date_stop": end},
        {
            "uuid": "pc-1",
            "date_start": datetime(2026, 9, 7, 10, 15),
            "date_stop": datetime(2026, 9, 7, 10, 45),
        },
    ]

    percentages, overall, sessions, pc_count = _calculate_hourly_utilization(rows, start, end, 1)

    assert percentages[(0, 10)] == 100
    assert overall == 100
    assert sessions == 2
    assert pc_count == 1


def test_pc_heatmap_hours_merge_overlapping_sessions():
    intervals = [
        (datetime(2026, 9, 7, 10, 0), datetime(2026, 9, 7, 12, 0)),
        (datetime(2026, 9, 7, 11, 0), datetime(2026, 9, 7, 13, 0)),
        (datetime(2026, 9, 7, 15, 0), datetime(2026, 9, 7, 16, 30)),
    ]

    assert _merged_occupied_seconds(intervals) / 3600 == 4.5
