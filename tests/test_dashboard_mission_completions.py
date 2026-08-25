from datetime import datetime

import pytest

from app.services import dashboard


def _mission(metric, *, mission_id=1, target=1, config=None):
    return {
        "id": mission_id,
        "target_metric": metric,
        "target_amount": target,
        "start_at": None,
        "end_at": None,
        "config": config or {},
    }


SESSIONS = [
    {"date_start": datetime(2026, 8, 10, 10, 0), "date_stop": datetime(2026, 8, 10, 13, 30)},
    {"date_start": datetime(2026, 8, 15, 23, 0), "date_stop": datetime(2026, 8, 16, 2, 0)},
    {"date_start": datetime(2026, 8, 16, 12, 0), "date_stop": datetime(2026, 8, 16, 13, 0)},
]
SPINS = [datetime(2026, 8, 11, 12, 0), datetime(2026, 8, 12, 12, 0)]
CASE_OPENINGS = [
    {"case_id": 5, "created_at": datetime(2026, 8, 13, 12, 0)},
    {"case_id": 7, "created_at": datetime(2026, 8, 14, 12, 0)},
]


@pytest.mark.parametrize(
    ("mission", "expected_completed_at"),
    [
        (_mission("visits_count", target=2), datetime(2026, 8, 15, 23, 0)),
        (
            _mission(
                "sessions_started_in_time_range_count", target=2, config={"time_start": "10:00", "time_end": "14:00"}
            ),
            datetime(2026, 8, 16, 12, 0),
        ),
        (
            _mission(
                "session_hours_in_time_range_total", target=4, config={"time_start": "10:00", "time_end": "14:00"}
            ),
            datetime(2026, 8, 16, 12, 0),
        ),
        (_mission("night_visits_count"), datetime(2026, 8, 15, 23, 0)),
        (_mission("weekend_visits_count"), datetime(2026, 8, 15, 23, 0)),
        (_mission("long_visits_count", config={"min_hours": 3}), datetime(2026, 8, 10, 10, 0)),
        (_mission("visits_min_hours_count", target=2, config={"min_hours": 3}), datetime(2026, 8, 15, 23, 0)),
        (_mission("weekday_visits_min_hours_count", config={"min_hours": 3}), datetime(2026, 8, 10, 10, 0)),
        (_mission("weekend_visits_min_hours_count", config={"min_hours": 3}), datetime(2026, 8, 15, 23, 0)),
        (_mission("total_hours", target=6), datetime(2026, 8, 15, 23, 0)),
        (_mission("night_hours_total", target=2), datetime(2026, 8, 15, 23, 0)),
        (_mission("day_hours_total", target=3), datetime(2026, 8, 10, 10, 0)),
        (_mission("consecutive_days_count", target=2), datetime(2026, 8, 16, 12, 0)),
        (_mission("wheel_spins_count", target=2), datetime(2026, 8, 12, 12, 0)),
        (_mission("case_openings_count", target=2), datetime(2026, 8, 14, 12, 0)),
        (_mission("specific_case_openings_count", config={"case_id": 7}), datetime(2026, 8, 14, 12, 0)),
    ],
)
def test_owner_mission_completion_calculator_supports_all_mission_metrics(mission, expected_completed_at):
    completed_at = dashboard._get_mission_completion_at_from_preloaded(
        guest_id=1,
        club_id=1,
        mission=mission,
        guest_sessions=SESSIONS,
        guest_spins=SPINS,
        guest_case_openings=CASE_OPENINGS,
        active_missions=[mission],
        completion_cache={},
    )

    assert completed_at == expected_completed_at


def test_owner_mission_completion_calculator_supports_completed_missions_count():
    visits_mission = _mission("visits_count", mission_id=1, target=1)
    case_mission = _mission("case_openings_count", mission_id=2, target=1)
    meta_mission = _mission("completed_missions_count", mission_id=3, target=2)
    active_missions = [visits_mission, case_mission, meta_mission]

    completed_at = dashboard._get_mission_completion_at_from_preloaded(
        guest_id=1,
        club_id=1,
        mission=meta_mission,
        guest_sessions=SESSIONS,
        guest_spins=SPINS,
        guest_case_openings=CASE_OPENINGS,
        active_missions=active_missions,
        completion_cache={},
    )

    assert completed_at == datetime(2026, 8, 13, 12, 0)


def test_utc_event_period_uses_club_local_boundaries():
    mission = {
        "club_timezone": "Asia/Yekaterinburg",
        "start_at": datetime(2026, 8, 25, 12, 0),
        "end_at": datetime(2026, 8, 25, 18, 0),
    }

    assert dashboard._event_allowed_by_mission_period(datetime(2026, 8, 25, 6, 59), mission) is False
    assert dashboard._event_allowed_by_mission_period(datetime(2026, 8, 25, 7, 0), mission) is True
    assert dashboard._event_allowed_by_mission_period(datetime(2026, 8, 25, 13, 0), mission) is True
    assert dashboard._event_allowed_by_mission_period(datetime(2026, 8, 25, 13, 1), mission) is False
