from datetime import datetime, timedelta

from app.services.monthly_reports import build_report_from_sources, month_bounds


def session(guest_id, start, hours=1):
    return {"guest_id": guest_id, "date_start": start, "date_stop": start + timedelta(hours=hours)}


def test_month_bounds_handles_december():
    assert month_bounds(2026, 12) == (datetime(2026, 12, 1), datetime(2027, 1, 1))


def test_report_uses_visits_cohorts_and_seven_day_crm_attribution():
    sources = {
        "sessions": [
            session(1, datetime(2026, 8, 2, 10)),
            session(1, datetime(2026, 8, 2, 12)),  # same visit: exactly two-hour gap
            session(1, datetime(2026, 8, 10, 10)),
            session(1, datetime(2026, 9, 5, 10)),
            session(2, datetime(2026, 7, 5, 10)),
            session(2, datetime(2026, 8, 8, 10)),
            session(3, datetime(2026, 8, 20, 10)),
            session(3, datetime(2026, 9, 10, 10)),  # outside seven-day CRM window
        ],
        "module_registrations": [{"guest_id": 1, "registered_at": datetime(2026, 8, 2, 11), "is_estimated": 0}],
        "lifecycle_events": [
            {"guest_id": 2, "to_status": "REACTIVATED", "changed_at": datetime(2026, 8, 8), "reconstructed": 0},
            {"guest_id": 4, "to_status": "CHURNED", "changed_at": datetime(2026, 8, 22), "reconstructed": 0},
        ],
        "score_history": [],
        "case_openings": [
            {"guest_id": 1, "created_at": datetime(2026, 8, 4)},
            {"guest_id": 1, "created_at": datetime(2026, 8, 5)},
        ],
        "wheel_spins": [],
        "mission_completions": [{"guest_id": 2, "completed_at": datetime(2026, 8, 9)}],
        "topups": [
            {"guest_id": 1, "amount": 500, "topup_at": datetime(2026, 8, 11)},
            {"guest_id": 2, "amount": 300, "topup_at": datetime(2026, 8, 9)},
        ],
        "mailing_recipients": [
            {
                "mailing_id": 7,
                "guest_id": 1,
                "status": "sent",
                "interaction_at": datetime(2026, 8, 4),
                "filters_json": '{"auto_mailing":"lost_60d"}',
                "scenario_title": "Возврат потерянных",
            },
            {
                "mailing_id": 7,
                "guest_id": 3,
                "status": "sent",
                "interaction_at": datetime(2026, 8, 21),
                "filters_json": '{"auto_mailing":"lost_60d"}',
                "scenario_title": "Возврат потерянных",
            },
        ],
    }
    report = build_report_from_sources(
        sources,
        {"club_id": 1, "name": "Тестовый клуб", "timezone": "Europe/Moscow"},
        2026,
        8,
        generated_at=datetime(2026, 9, 14),
    )

    assert report["metrics"]["unique_guests"]["value"] == 3
    assert report["metrics"]["new_guests"]["value"] == 2
    assert report["retention"]["new_guests"] == {
        "first": 2,
        "second": 2,
        "third": 1,
        "second_percent": 100.0,
        "third_percent": 50.0,
    }
    assert report["retention"]["all_guests"][0]["count"] == 3
    assert report["retention"]["all_guests"][1]["count"] == 1
    assert report["crm"]["automatic"][0]["returned"] == 1
    assert report["crm"]["automatic"][0]["conversion_percent"] == 50.0
    assert report["engaged_revenue"]["amount"] == 800


def test_report_keeps_no_data_sections_valid():
    report = build_report_from_sources(
        {},
        {"club_id": 9, "name": "Пустой клуб", "timezone": "Europe/Moscow"},
        2026,
        8,
        generated_at=datetime(2026, 9, 14),
    )
    assert report["health"]["average"] is None
    assert report["crm"]["best_manual"] is None
    assert report["gamification"]["wheel"]["participants"] == 0
    assert report["data_quality"]
