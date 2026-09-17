from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from app.services.guest_pulse import calculate_club, previous_states
from app.services.guest_pulse_filters import deviations, parse_filters, select
from app.services.guest_pulse_scores import (
    add_history,
    audience,
    engagement,
    health,
    lifecycle,
    value_scores,
    visit_features,
)
from app.services.visits import collapse_sessions_to_visits

NOW = datetime(2026, 9, 11, 12)


def visits(ages, hours=2):
    return [
        {
            "date_start": NOW - timedelta(days=d, hours=hours),
            "date_stop": NOW - timedelta(days=d),
            "played_hours": hours,
        }
        for d in sorted(ages, reverse=True)
    ]


def features(**overrides):
    result = visit_features(visits(range(0, 91, 5)), NOW)
    result.update(overrides)
    return result


def row(h=60, v=75, e=35, status="ACTIVE"):
    return {
        "guest_id": 1,
        "health": {"score": h},
        "value": {"score": v},
        "engagement": {"score": e},
        "lifecycle_status": status,
        "audience_type": "loyal",
    }


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (0.75, 100),
        (0.7501, 90),
        (1, 90),
        (1.001, 75),
        (1.25, 75),
        (1.251, 60),
        (1.5, 60),
        (1.501, 40),
        (2, 40),
        (2.001, 20),
        (3, 20),
        (3.001, 0),
    ],
)
def test_recency_continuous_boundaries(ratio, expected):
    assert health(features(gap_ratio=ratio))["recency"] == expected


@pytest.mark.parametrize("current,expected", [(11, 100), (10, 90), (9, 90), (8, 70), (5, 45), (3, 20), (0, 0)])
def test_frequency_previous_sixty_days_excludes_current(current, expected):
    result = health(features(visits_30d=current, visits_90d=current + 20))
    assert result["frequency"] == expected


def test_one_visit_null_even_when_old_and_we_have_telegram_or_money():
    f = visit_features(visits([100]), NOW)
    h = health(f)
    assert h["score"] is None
    assert lifecycle(f, h, NOW)["lifecycle_status"] == "NEW"


def test_partial_health_normalizes_available_weights():
    h = health(features(age_days=10, visits_total=2, gap_cv=None, gap_ratio=1))
    assert h["frequency"] is None and h["trend"] is None and h["consistency"] is None
    assert h["score"] == 90
    assert h["preliminary"]


def test_hard_rules_override_good_other_components():
    assert health(features(gap_ratio=3.1))["score"] <= 25
    assert health(features(days_since_last_visit=60))["score"] <= 15


def test_long_gaps_outside_history_do_not_distort_typical_gap():
    f = visit_features(visits([400, 85, 80, 75, 70]), NOW)
    assert f["typical_gap_days"] == 5


def test_stable_trend_is_eighty():
    h = health(features(visits_30d=6, visits_60d=12, played_hours_30d=12, played_hours_60d=24))
    assert h["trend"] == 80


def test_session_normalization_ignores_bad_open_and_future_rows_and_unions_hours():
    rows = [
        {"date_start": NOW, "date_stop": NOW + timedelta(hours=1)},
        {"date_start": NOW + timedelta(minutes=30), "date_stop": NOW + timedelta(hours=2)},
        {"date_start": NOW + timedelta(hours=3), "date_stop": NOW + timedelta(hours=4)},
        {"date_start": None, "date_stop": NOW},
        {"date_start": NOW, "date_stop": None},
        {"date_start": NOW, "date_stop": NOW - timedelta(hours=1)},
    ]
    normalized = collapse_sessions_to_visits(rows)
    assert len(normalized) == 1
    assert normalized[0]["played_hours"] == 3
    assert visit_features(normalized, NOW)["visits_total"] == 0


def test_reactivation_requires_new_visit_and_expires():
    old = {
        "lifecycle_status": "CHURNED",
        "lifecycle_status_changed_at": NOW - timedelta(days=20),
        "last_visit_date": NOW - timedelta(days=40),
    }
    f = features(last_visit_date=NOW - timedelta(days=1))
    state = lifecycle(f, health(f), NOW, old)
    assert state["lifecycle_status"] == "REACTIVATED"
    assert lifecycle(f, health(f), NOW + timedelta(days=13), state)["lifecycle_status"] != "REACTIVATED"
    old["last_visit_date"] = f["last_visit_date"]
    assert lifecycle(f, health(f), NOW, old)["lifecycle_status"] != "REACTIVATED"


def test_value_reference_excludes_one_visit_and_equal_values_tie():
    rows = [dict(guest_id=i, visits_90d=2, revenue_90d=100, played_hours_90d=2, avg_check_90d=50) for i in (1, 2)]
    rows.append(dict(guest_id=3, visits_90d=1, revenue_90d=9999, played_hours_90d=90, avg_check_90d=9999))
    scores = value_scores(rows)
    assert scores[1]["score"] == scores[2]["score"] == 0
    assert scores[3]["reference_count"] == 2
    assert scores[3]["percentiles"]["revenue_90d"] == 100


def test_value_missing_money_normalizes_available_weights():
    scores = value_scores(
        [
            dict(guest_id=1, visits_90d=3, revenue_90d=None, played_hours_90d=3, avg_check_90d=None),
            dict(guest_id=2, visits_90d=2, revenue_90d=None, played_hours_90d=2, avg_check_90d=None),
        ]
    )
    assert scores[1]["score"] == 50
    assert scores[1]["percentiles"]["revenue_90d"] is None


def test_engagement_all_components_and_ignores_future():
    events = [{"kind": "mission", "at": NOW - timedelta(days=d)} for d in (0, 1, 2)]
    events += [{"kind": "case", "at": NOW - timedelta(days=d)} for d in (0, 1, 2, 3, 4)]
    events += [
        {"kind": "contract_selected", "at": NOW - timedelta(days=1)},
        {"kind": "contract_completed", "at": NOW - timedelta(days=1)},
    ]
    events.append({"kind": "case", "at": NOW + timedelta(days=1)})
    e = engagement(events, True, NOW)
    assert e["score"] == 100
    assert e["missions_completed_30d"] == 3 and e["cb_actions_30d"] == 7 and e["current_streak"] == 5
    assert e["contracts_selected_30d"] == 1
    assert e["contracts_completed_30d"] == 1
    assert engagement(events, None, NOW)["score"] is None


@pytest.mark.parametrize(
    "h,v,e,status,expected",
    [
        (None, 100, 100, "NEW", "new"),
        (10, 100, 100, "CHURNED", "churned"),
        (59, 75, 10, "ACTIVE", "valuable_risk"),
        (60, 100, 34, "ACTIVE", "low_engagement"),
        (60, 75, 35, "ACTIVE", "loyal"),
        (59, 74, 100, "ACTIVE", "risk"),
        (60, 74, 35, "ACTIVE", "other"),
    ],
)
def test_audience_precedence(h, v, e, status, expected):
    assert audience(row(h, v, e, status)) == expected


def test_history_previous_thirty_days_seven_valid_samples_and_zero_baseline():
    r = row(60, 0, 50)
    snapshots = [
        dict(snapshot_date=NOW.date() - timedelta(days=d), health_score=80, value_score=0, engagement_score=None)
        for d in range(1, 8)
    ]
    snapshots += [
        dict(snapshot_date=NOW.date(), health_score=1, value_score=99, engagement_score=10),
        dict(snapshot_date=NOW.date() - timedelta(days=31), health_score=1, value_score=99, engagement_score=10),
    ]
    add_history(r, snapshots, NOW.date())
    assert r["health"]["baseline_30d"] == 80
    assert r["health"]["deviation_ratio"] == 0.25
    assert r["health"]["deviation_points"] == -20
    assert r["health"]["deviation_percent"] == -25
    assert r["health"]["deviation_direction"] == "DOWN"
    assert r["value"]["deviation_ratio"] == 0
    assert r["engagement"]["baseline_30d"] is None
    assert len(deviations(r, parse_filters({}))) == 1


def test_full_filters_include_null_and_ranges_exclude_it_without_mutating_scores():
    r = row(None, 90, 20, "NEW")
    r["audience_type"] = "new"
    assert select([r], parse_filters({})) == [r]
    assert select([r], parse_filters({"health_min": 1})) == []
    assert r["health"]["score"] is None


@pytest.mark.parametrize(
    "args",
    [
        {"health_min": 70, "health_max": 50},
        {"value_min": "NaN"},
        {"engagement_max": "inf"},
        {"metric": "bad"},
        {"audience_type": "bad"},
        {"health_min": -1},
        {"segment": "bad"},
        {"deviation_direction": "sideways"},
    ],
)
def test_invalid_filters_rejected(args):
    with pytest.raises(ValueError):
        parse_filters(args)


def test_all_deviations_returns_every_matching_score_and_ignores_audience_filters():
    r = row()
    for k in ("health", "value", "engagement"):
        r[k]["deviation_ratio"] = 0.25
    f = parse_filters({"health_min": 90})
    assert len(select([r], f, "deviations")[0]["deviations"]) == 3


def test_deviation_direction_and_numeric_boundaries_are_applied_together():
    r = row()
    r["has_telegram"] = True
    r["health"].update(deviation_ratio=0.15, deviation_direction="UP")
    r["value"].update(deviation_ratio=0.30, deviation_direction="DOWN")
    r["engagement"].update(deviation_ratio=0.51, deviation_direction="UP")

    positive = deviations(r, parse_filters({"deviation_direction": "up"}))
    negative = deviations(r, parse_filters({"deviation_direction": "down"}))

    assert [item["metric"] for item in positive] == ["health"]
    assert [item["metric"] for item in negative] == ["value"]

    r["has_telegram"] = False
    contactable = parse_filters({"deviation_telegram_only": "true"})
    assert deviations(r, contactable) == []


def test_replay_no_lookahead_excludes_no_visit_guests():
    grouped = {key: defaultdict(list) for key in ("sessions", "events", "topups")}
    grouped["sessions"][1] = [
        {"date_start": v["date_start"], "date_stop": v["date_stop"]} for v in visits([70, 60, 50, 20, 2])
    ]
    grouped["sessions"][1].append({"date_start": NOW + timedelta(days=1), "date_stop": NOW + timedelta(days=2)})
    grouped["topups"][1] = [{"topup_at": NOW - timedelta(days=1), "amount": 1000}]
    sources = ([{"guest_id": 1, "fio": "Тест", "telegram_id": 100}, {"guest_id": 2, "fio": "Нет визитов"}], grouped)
    historical = calculate_club(sources, NOW - timedelta(days=30), historical=True)
    assert len(historical) == 1
    assert historical[0]["visits"]["visits_total"] == 3
    assert historical[0]["value"]["revenue_90d"] == 0
    assert historical[0]["engagement"]["score"] == 0
    assert historical[0]["engagement"]["estimated"]
    current = calculate_club(sources, NOW, previous_states(historical))
    assert current[0]["visits"]["visits_total"] == 5
    assert current[0]["value"]["revenue_90d"] == 1000
