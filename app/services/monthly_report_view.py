"""Presentation-only helpers for monthly report previews and PDF rendering."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

METRIC_LABELS = {
    "unique_guests": "Уникальные гости",
    "new_guests": "Новые гости",
    "new_module_guests": "Новые в Cyber Bonus",
    "reactivated_guests": "Реактивированные",
    "average_visits": "Визитов на гостя",
    "lost_guests": "Перешли в Lost",
}


def format_number(value, digits=0):
    if value is None:
        return "—"
    number = float(value)
    text = f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.rstrip("0").rstrip(",") if digits else text


def format_money(value):
    return f"{format_number(value)} руб." if value is not None else "—"


def format_percent(value):
    return f"{format_number(value, 1)}%" if value is not None else "—"


def change_label(change):
    percent = (change or {}).get("percent")
    if percent is None:
        return "Нет данных для сравнения"
    sign = "+" if percent > 0 else ""
    return f"{sign}{format_number(percent, 1)}% к прошлому месяцу"


def build_monthly_report_view(data):
    view = deepcopy(data)
    view["metric_cards"] = [
        {
            "code": code,
            "label": METRIC_LABELS[code],
            "value": format_number(metric["value"], 2 if code == "average_visits" else 0),
            "change": change_label(metric.get("change")),
            "trend": (
                "up"
                if (metric.get("change") or {}).get("absolute", 0) > 0
                else "down" if (metric.get("change") or {}).get("absolute", 0) < 0 else "flat"
            ),
        }
        for code, metric in data["metrics"].items()
    ]
    view["generated_label"] = datetime.fromisoformat(data["period"]["generated_at"]).strftime("%d.%m.%Y %H:%M")
    view["health"]["average_label"] = format_number(view["health"].get("average"), 1)
    view["health"]["previous_label"] = format_number(view["health"].get("previous_average"), 1)
    view["engaged_revenue"]["amount_label"] = format_money(view["engaged_revenue"].get("amount"))
    view["engaged_revenue"]["average_label"] = format_money(view["engaged_revenue"].get("average_per_guest"))
    impact = view["cyber_bonus_impact"]
    impact["reactivation"]["topup_label"] = format_money(impact["reactivation"].get("topup_amount"))
    impact["cases_to_topup"]["topup_label"] = format_money(impact["cases_to_topup"].get("topup_amount"))
    return view
