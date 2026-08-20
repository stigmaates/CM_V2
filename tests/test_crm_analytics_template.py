from flask import render_template

from app.main import app


def _base_template_context():
    return {
        "heatmap": {"total_visits": 0, "peak": {"day": "—", "hour": "—", "value": 0}, "hours": [], "grid": []},
        "pc_heatmap": {
            "total_hours_display": "0",
            "total_sessions": 0,
            "peak": {"name": "—", "hours_display": "0"},
            "pcs": [],
        },
        "filter_fields": [],
        "message_variables": [],
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
            crm_pulse_groups=[
                {
                    "key": "rare__base",
                    "old_label": "Редкие",
                    "new_label": "База",
                    "direction": "up",
                    "total_count": 2,
                    "telegram_count": 1,
                    "recent_auto_count": 1,
                    "guests": [
                        {
                            "guest_id": 10,
                            "fio": "Иванов Иван",
                            "first_name": "Иван",
                            "recent_auto_mailing_title": "Вернуть гостей после неактива",
                        }
                    ],
                }
            ],
            initial_analysis={
                "audience": {"total": 2, "telegram": 1, "telegram_percent": 50},
                "funnel": [],
                "metrics": [],
            },
            manual_campaigns=[],
        )

    assert "Анализ" in html
    assert "Период воронки" in html
    assert 'data-period="all"' in html
    assert "Сохранить когорту" in html
    assert "Тестовая когорта" in html
    assert "Пульс базы" in html
    assert "Редкие" in html
    assert "Взаимодействовать" in html
    assert "crm-cohort-delete" in html
    assert "crm_analytics.js" in html
    assert "1</span><small>/2" in html


def test_crm_analytics_renders_manual_campaign_passports():
    campaigns = []
    for campaign_id in range(12, 18):
        campaigns.append(
            {
                "campaign_type": "mailing",
                "campaign_id": campaign_id,
                "status": "completed",
                "token_amount": 0,
                "created_at": "2026-08-01 12:00:00",
                "summary": {
                    "recipients_count": 10,
                    "delivered_count": 9,
                    "visited_count": 4,
                    "topped_up_count": 2,
                    "bonus_spent": 0,
                    "token_spent": 0,
                },
            }
        )

    with app.test_request_context("/owner/crm-analytics"):
        html = render_template(
            "owner/crm_analytics.html",
            **_base_template_context(),
            audience={},
            cohorts=[],
            crm_pulse_groups=[],
            initial_analysis={
                "audience": {"total": 0, "telegram": 0, "telegram_percent": 0},
                "funnel": [],
                "metrics": [],
            },
            manual_campaigns=campaigns,
        )

    assert "Аналитика коммуникаций" in html
    assert "Рассылка #12" in html
    assert "Рассылка #17" in html
    assert "is-campaign-hidden" in html
    assert "Показать все" in html
    assert "crmCampaignModal" in html
    assert "Ручные" in html
    assert "Авторассылки" in html
    assert 'id="crmAutoCampaignsPanel"' in html
    assert "Уникальных получателей" not in html
