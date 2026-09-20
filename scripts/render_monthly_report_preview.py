"""Render a deterministic visual preview without database access."""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.monthly_report_pdf import render_monthly_report_pdf
from app.services.monthly_report_view import build_monthly_report_view


def sample():
    metrics = {}
    for code, current, previous in (
        ("unique_guests", 612, 566),
        ("new_guests", 120, 111),
        ("new_module_guests", 74, 63),
        ("reactivated_guests", 31, 23),
        ("average_visits", 2.97, 2.61),
        ("lost_guests", 18, 26),
    ):
        metrics[code] = {
            "value": current,
            "previous": previous,
            "change": {"absolute": current - previous, "percent": round((current / previous - 1) * 100, 1)},
        }
    return {
        "version": "v1",
        "club": {"id": 1, "name": "WALLZ Самара", "timezone": "Europe/Samara"},
        "period": {
            "year": 2026,
            "month": 8,
            "title": "Август 2026",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "generated_at": datetime(2026, 9, 14, 12, 30).isoformat(),
        },
        "metrics": metrics,
        "pulse": [
            {"code": "new", "label": "Новые / формируют привычку", "count": 207, "change": 34},
            {"code": "churned", "label": "Потерянные", "count": 84, "change": -8},
            {"code": "valuable_risk", "label": "Ценные в зоне риска", "count": 19, "change": -3},
            {"code": "low_engagement", "label": "Активные, но не вовлечены", "count": 132, "change": 12},
            {"code": "loyal", "label": "Лояльное ядро", "count": 71, "change": 7},
            {"code": "risk", "label": "В зоне риска", "count": 65, "change": -12},
            {"code": "other", "label": "Остальные", "count": 34, "change": 4},
        ],
        "health": {
            "average": 72,
            "previous_average": 68,
            "change": 4,
            "scored_guests": 508,
            "distribution": [
                {
                    "code": "healthy",
                    "label": "Здоровая база",
                    "range": "80-100",
                    "description": "Гости приходят регулярно, поведение устойчивое.",
                    "count": 208,
                    "percent": 41,
                },
                {
                    "code": "stable",
                    "label": "Стабильная база",
                    "range": "60-79",
                    "description": "Посещения стабильны, выраженного риска ухода нет.",
                    "count": 163,
                    "percent": 32,
                },
                {
                    "code": "risk",
                    "label": "Зона риска",
                    "range": "40-59",
                    "description": "Регулярность снизилась: стоит вернуть внимание гостя.",
                    "count": 97,
                    "percent": 19,
                },
                {
                    "code": "critical",
                    "label": "Критическая зона",
                    "range": "ниже 40",
                    "description": "Высокий риск ухода или длительное отсутствие.",
                    "count": 40,
                    "percent": 8,
                },
            ],
        },
        "retention": {
            "new_guests": {"first": 120, "second": 68, "third": 41, "second_percent": 56.7, "third_percent": 34.2},
            "all_guests": [
                {"visits": 1, "count": 612, "percent": 100, "step_percent": 100},
                {"visits": 2, "count": 381, "percent": 62.3, "step_percent": 62.3},
                {"visits": 3, "count": 244, "percent": 39.9, "step_percent": 64.0},
                {"visits": 4, "count": 156, "percent": 25.5, "step_percent": 63.9},
                {"visits": 5, "count": 93, "percent": 15.2, "step_percent": 59.6},
            ],
        },
        "crm": {
            "attribution_days": 7,
            "automatic": [
                {
                    "title": "Возврат потерянных",
                    "sent": 96,
                    "returned": 31,
                    "conversion_percent": 32.3,
                    "topup_amount": 48600,
                },
                {
                    "title": "После первого визита",
                    "sent": 118,
                    "returned": 54,
                    "conversion_percent": 45.8,
                    "topup_amount": 28900,
                },
            ],
            "best_manual": {
                "title": "Летний апгрейд",
                "audience": "Активные гости",
                "sent": 184,
                "returned": 47,
                "conversion_percent": 25.5,
                "topup_amount": 55700,
            },
        },
        "gamification": {
            "cases": {
                "participants": 214,
                "actions": 486,
                "repeat_participants": 119,
                "average_actions": 2.27,
                "engagement_percent": 35,
                "guest_ids": [],
            },
            "wheel": {
                "participants": 91,
                "actions": 134,
                "repeat_participants": 31,
                "average_actions": 1.47,
                "engagement_percent": 14.9,
                "guest_ids": [],
            },
            "missions": {
                "participants": 76,
                "actions": 108,
                "repeat_participants": 24,
                "average_actions": 1.42,
                "engagement_percent": 12.4,
                "guest_ids": [],
            },
        },
        "engaged_revenue": {"guests": 186, "topped_up_guests": 137, "amount": 186400, "average_per_guest": 1002.15},
        "cyber_bonus_impact": {
            "reactivation": {"sent": 96, "returned": 31, "conversion_percent": 32.3, "topup_amount": 48600},
            "cases_to_topup": {
                "case_users": 214,
                "topped_up_users": 137,
                "conversion_percent": 64,
                "topup_amount": 141300,
            },
            "engaged_frequency": {
                "guests": 238,
                "current": 3.1,
                "previous": 2.4,
                "change": 0.7,
                "change_percent": 29.2,
            },
        },
        "data_quality": [],
    }


if __name__ == "__main__":
    target = Path("output/pdf/cyber_bonus_monthly_report_preview.pdf")
    render_monthly_report_pdf(build_monthly_report_view(sample()), target)
    print(target.resolve())
