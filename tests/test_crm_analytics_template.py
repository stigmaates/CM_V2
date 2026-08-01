from flask import render_template

from app.main import app


def _base_template_context():
    return {
        "heatmap": {"total_visits": 0, "peak": {"day": "—", "hour": "—", "value": 0}, "hours": [], "grid": []},
        "pc_heatmap": {"total_hours_display": "0", "total_sessions": 0, "peak": {"name": "—", "hours_display": "0"}, "pcs": []},
        "filter_fields": [],
        "selected_period": 30,
        "telegram_only": False,
    }


def test_crm_analytics_renders_cohort_analysis_block():
    with app.test_request_context("/owner/crm-analytics"):
        html = render_template(
            "owner/crm_analytics.html",
            **_base_template_context(),
            audience={
                "top": 2,
                "top_telegram": 1,
                "base": 0,
                "base_telegram": 0,
                "rare": 0,
                "rare_telegram": 0,
                "risk": 0,
                "risk_telegram": 0,
                "lost": 0,
                "lost_telegram": 0,
                "dead": 0,
                "dead_telegram": 0,
                "no_visits": 0,
                "no_visits_telegram": 0,
                "total": 2,
                "total_telegram": 1,
            },
            cohorts=[{"id": 1, "name": "Тестовая когорта", "rules_json": {"rules": []}}],
            initial_analysis={
                "audience": {"total": 2, "telegram": 1, "telegram_percent": 50},
                "funnel": [],
                "metrics": [],
            },
            manual_campaigns=[],
        )

    assert "Анализ" in html
    assert "Период воронки" in html
    assert "data-period=\"all\"" in html
    assert "Сохранить когорту" in html
    assert "Тестовая когорта" in html
    assert "crm-cohort-delete" in html
    assert "crm_analytics.js" in html
    assert "1</span><small>/2" in html


def test_crm_analytics_renders_manual_campaign_passports():
    with app.test_request_context("/owner/crm-analytics"):
        html = render_template(
            "owner/crm_analytics.html",
            **_base_template_context(),
            audience={},
            cohorts=[],
            initial_analysis={
                "audience": {"total": 0, "telegram": 0, "telegram_percent": 0},
                "funnel": [],
                "metrics": [],
            },
            manual_campaigns=[
                {
                    "campaign_type": "mailing",
                    "campaign_id": 12,
                    "status": "completed",
                    "token_amount": 0,
                    "created_at": "2026-08-01 12:00:00",
                    "summary": {
                        "recipients_count": 10,
                        "delivered_count": 9,
                        "visited_count": 4,
                        "topped_up_count": 2,
                        "bonus_spent": 0,
                    },
                }
            ],
        )

    assert "Аналитика коммуникаций" in html
    assert "Рассылка #12" in html
    assert "crmCampaignModal" in html
