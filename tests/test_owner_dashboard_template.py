from flask import render_template

from app.main import app


def test_owner_dashboard_renders_case_period_chart_values_key():
    stats = {
        "period_days": 30,
        "guests_current": 0,
        "guests_diff": 0,
        "guests_diff_percent": 0,
        "retention_current": 0,
        "retention_diff": 0,
        "avg_check_current": 0,
        "avg_check_diff": 0,
        "avg_check_diff_percent": 0,
        "csi_percent": 0,
        "csi_linked_guests": 0,
        "csi_total_guests": 0,
        "mailing_count": 0,
        "kpi_sparklines": {"guests_path": "", "retention_path": "", "avg_check_path": ""},
        "visit_streak_funnel": [],
    }
    engagement = {
        "wheel": {"total_guests": 0, "involved_guests": 0, "engagement_percent": 0, "returned_guests": 0},
        "cases": {"total_guests": 0, "involved_guests": 0, "engagement_percent": 0, "returned_guests": 0},
        "missions": {"total_guests": 0, "involved_guests": 0, "engagement_percent": 0, "returned_guests": 0},
    }
    first_visit_feedback = {
        "avg_rating": 0,
        "avg_rating_display": "0",
        "total_responses": 0,
        "positive_count": 0,
        "negative_count": 0,
        "positive_preview": [],
        "negative_preview": [],
        "positive_messages": [],
        "negative_messages": [],
        "period_days": 30,
    }

    with app.test_request_context("/owner/dashboard"):
        html = render_template(
            "owner/dashboard.html",
            club={"name": "WALLZ"},
            stats=stats,
            engagement=engagement,
            engagement_all_time_data=engagement,
            case_openings_chart={"items": [], "total_openings": 0, "unique_openers": 0, "period_days": 30},
            case_openings_period_chart={
                "bucket": "month",
                "bucket_label": "Месяцы",
                "labels": ["08.2026"],
                "series": [{"name": "Test Case", "values": [3], "color": "#8f5bff", "total": 3}],
                "max_value": 3,
            },
            wheel_spins_period_chart={
                "bucket": "month",
                "bucket_label": "Месяцы",
                "items": [{"label": "08.2026", "count": 2, "height": 100}],
                "max_value": 2,
                "total": 2,
            },
            mission_completions_chart={"items": [], "total_completions": 0, "period_days": 30},
            first_visit_feedback=first_visit_feedback,
            selected_period=30,
            selected_case_bucket="month",
            selected_wheel_bucket="month",
            active_engagement_tab="cases",
        )

    assert "Открытия кейсов по периодам" in html
    assert "Test Case" in html
    assert "08.2026" in html
