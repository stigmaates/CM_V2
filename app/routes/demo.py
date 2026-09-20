from __future__ import annotations

import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session, url_for as flask_url_for


demo_bp = Blueprint("demo", __name__, url_prefix="/demo")

PAGE_MAP = {
    "overview": ("owner/dashboard.html", "dashboard", {}),
    "dashboard": ("owner/dashboard.html", "dashboard", {}),
    "cohorts": ("owner/crm_analytics.html", "crm", {"analytics_section": "cohorts"}),
    "heatmaps": ("owner/crm_analytics.html", "crm", {"analytics_section": "heatmaps"}),
    "communications": ("owner/crm_analytics.html", "crm", {"analytics_section": "communications"}),
    "guest-pulse": ("owner/guest_pulse.html", "pulse", {}),
    "team": ("owner/team.html", "team", {}),
    "mailings": ("owner/mailing.html", "mailing", {}),
    "training": ("owner/training.html", "training", {}),
    "settings": ("owner/settings.html", "settings", {"tab": "club"}),
    "missions": ("owner/settings.html", "settings", {"tab": "missions"}),
    "contracts": ("owner/settings.html", "settings", {"tab": "contracts"}),
    "cases": ("owner/settings.html", "settings", {"tab": "wheel", "editor": "cases"}),
    "promotions": ("owner/promotions.html", "settings", {"tab": "wheel", "editor": "wheel"}),
    "guests": ("owner/settings.html", "settings", {"tab": "guests"}),
    "managed-drops": ("owner/settings.html", "settings", {"tab": "managed-drops"}),
}

DEMO_CASES = [
    {
        "id": 1, "name": "WALLZ CS2 Case", "description": "Кейс с игровыми призами и бонусами клуба.",
        "image_url": None, "badge_label": "Игровой", "badge_color": "#d7b900", "price_tokens": 3, "is_active": True,
        "items": [
            {"id": 11, "name": "100 КБ", "description": "Бонусы на баланс", "image_url": None, "bonus_amount": 100, "token_amount": 0, "contract_refresh_amount": 0, "probability": 45.0, "rarity_label": "Обычный", "is_active": True, "sort_order": 1},
            {"id": 12, "name": "+3 жетона", "description": "Жетоны для следующего открытия", "image_url": None, "bonus_amount": 0, "token_amount": 3, "contract_refresh_amount": 0, "probability": 30.0, "rarity_label": "Редкий", "is_active": True, "sort_order": 2},
            {"id": 13, "name": "Час игры", "description": "Приз выдаст администратор", "image_url": None, "bonus_amount": 0, "token_amount": 0, "contract_refresh_amount": 0, "probability": 20.0, "rarity_label": "Очень редкий", "is_active": True, "sort_order": 3},
            {"id": 14, "name": "Ночь в клубе", "description": "Главный приз кейса", "image_url": None, "bonus_amount": 0, "token_amount": 0, "contract_refresh_amount": 0, "probability": 5.0, "rarity_label": "Ультра редкий", "is_active": True, "sort_order": 4},
        ],
    },
    {
        "id": 2, "name": "Cyber Bonus Case", "description": "Бонусы и дополнительные жетоны.",
        "image_url": None, "badge_label": "Базовый", "badge_color": "#3498db", "price_tokens": 2, "is_active": True,
        "items": [
            {"id": 21, "name": "50 КБ", "description": "Бонусы на баланс", "image_url": None, "bonus_amount": 50, "token_amount": 0, "contract_refresh_amount": 0, "probability": 60.0, "rarity_label": "Обычный", "is_active": True, "sort_order": 1},
            {"id": 22, "name": "+5 жетонов", "description": "Редкий возврат жетонов", "image_url": None, "bonus_amount": 0, "token_amount": 5, "contract_refresh_amount": 0, "probability": 40.0, "rarity_label": "Редкий", "is_active": True, "sort_order": 2},
        ],
    },
]


def _demo_url_for(endpoint: str, **values) -> str:
    if endpoint == "static":
        return flask_url_for(endpoint, **values)
    mapping = {
        "owner.dashboard": "dashboard", "owner.analytics_cohorts": "cohorts",
        "owner.analytics_communications": "communications", "owner.analytics_heatmaps": "heatmaps",
        "owner.guest_pulse": "guest-pulse", "owner.promotions": "promotions",
        "owner.training": "training", "owner.settings": "settings", "owner.team": "team", "owner.mailing_page": "mailings",
    }
    if endpoint in mapping:
        page = mapping[endpoint]
        if endpoint == "owner.settings":
            tab = values.pop("tab", "club")
            page = {"missions": "missions", "contracts": "contracts", "wheel": "cases", "guests": "guests", "managed-drops": "managed-drops"}.get(tab, "settings")
        anchor = values.pop("_anchor", None)
        target = flask_url_for("demo.owner_page", page=page, **values)
        return f"{target}#{anchor}" if anchor else target
    if endpoint.startswith("owner."):
        return flask_url_for("demo.action", action=endpoint.removeprefix("owner."), **values)
    if endpoint.startswith("guest.api_"):
        return flask_url_for("demo.guest_api", path=endpoint.removeprefix("guest.api_"), **values)
    if endpoint in {"guest.logout", "guest.stop_test_mode", "auth.logout"}:
        return flask_url_for("demo.index")
    if endpoint.startswith("guest."):
        return flask_url_for("demo.guest")
    return flask_url_for(endpoint, **values)


def _common(page: str) -> dict:
    return {
        "demo_mode": True, "demo_page": page, "header_club_name": "DEMO CLUB",
        "header_user_name": "Демо-пользователь", "header_user_login": "demo",
        "url_for": _demo_url_for, "session": {"role": "owner", "name": "Демо-пользователь"},
    }


def _filter_fields() -> list[dict]:
    return [
        {"key": "visits_total", "label": "Количество визитов", "type": "number", "operators": [{"value": "gte", "label": "не меньше"}, {"value": "lte", "label": "не больше"}]},
        {"key": "has_telegram", "label": "Telegram", "type": "select", "options": [{"value": "1", "label": "подключён"}, {"value": "0", "label": "не подключён"}]},
        {"key": "avg_check", "label": "Среднее пополнение", "type": "number", "operators": [{"value": "gte", "label": "не меньше"}]},
    ]


def _message_variables() -> list[dict]:
    return [{"key": "first_name", "label": "Имя", "placeholder": "{first_name}"}, {"key": "club_name", "label": "Клуб", "placeholder": "{club_name}"}]


def _demo_date_range(default_days: int = 30):
    today = datetime.now().date()
    try:
        date_from = datetime.strptime(request.args.get("date_from", ""), "%Y-%m-%d").date()
        date_to = datetime.strptime(request.args.get("date_to", ""), "%Y-%m-%d").date()
        if date_to < date_from or (date_to - date_from).days > 365:
            raise ValueError
    except (TypeError, ValueError):
        date_to = today
        date_from = today - timedelta(days=default_days - 1)
    return date_from, date_to


def _dashboard_context() -> dict:
    period = request.args.get("period", 30, type=int)
    if period not in (7, 30, 90):
        period = 30
    date_from, date_to = _demo_date_range(period)
    period = (date_to - date_from).days + 1
    stats = {
        "period_days": period, "guests_current": 437, "guests_previous": 398, "guests_diff": 39, "guests_diff_percent": 9.8,
        "retention_current": 67.4, "retention_previous": 62.1, "retention_diff": 5.3,
        "avg_check_current": 684, "avg_check_previous": 621, "avg_check_diff": 63, "avg_check_diff_percent": 10.1,
        "csi_percent": 71.6, "csi_linked_guests": 313, "csi_total_guests": 437, "mailing_count": 1152,
        "kpi_sparklines": {"guests_path": "M0 45 C20 40 26 12 45 22 S72 52 88 25 S116 8 140 17", "retention_path": "M0 40 C20 35 28 45 44 30 S70 12 89 24 S117 40 140 9", "avg_check_path": "M0 42 C22 44 30 20 48 30 S73 46 90 19 S116 12 140 21"},
        "visit_streak_funnel": [{"label": f"{i}+ дней", "short_label": f"{i}+", "count": count, "height": height} for i, count, height in [(1, 383, 100), (2, 228, 72), (3, 164, 57), (4, 118, 45), (5, 83, 34), (6, 61, 27), (7, 44, 20)]],
    }
    engagement = {
        "scope": "period", "period_days": period,
        "wheel": {"total_guests": 437, "involved_guests": 248, "engagement_percent": 56.8, "returned_guests": 177},
        "cases": {"total_guests": 437, "involved_guests": 291, "engagement_percent": 66.6, "returned_guests": 208},
        "missions": {"total_guests": 437, "involved_guests": 203, "engagement_percent": 46.5, "returned_guests": 151},
    }
    all_time = {**engagement, "scope": "all_time", "wheel": {"total_guests": 1842, "involved_guests": 1117, "engagement_percent": 60.6, "returned_guests": 893}, "cases": {"total_guests": 1842, "involved_guests": 1259, "engagement_percent": 68.3, "returned_guests": 946}, "missions": {"total_guests": 1842, "involved_guests": 987, "engagement_percent": 53.6, "returned_guests": 741}}
    positive = [{"guest_id": 1, "rating": 5, "text": "Понравились компьютеры и атмосфера.", "short_text": "Понравились компьютеры и атмосфера.", "date": "18.09.2026 21:14"}, {"guest_id": 2, "rating": 4, "text": "Добавьте больше напитков без сахара.", "short_text": "Добавьте больше напитков без сахара.", "date": "17.09.2026 18:42"}]
    negative = [{"guest_id": 3, "rating": 3, "text": "Долго ждал свободный компьютер.", "short_text": "Долго ждал свободный компьютер.", "date": "16.09.2026 20:05"}]
    return {
        **_common("dashboard"), "selected_period": period, "stats": stats, "engagement": engagement, "engagement_all_time_data": all_time,
        "selected_date_from": date_from.isoformat(),
        "selected_date_to": date_to.isoformat(),
        "selected_period_label": f"{date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
        "dashboard_max_date": datetime.now().date().isoformat(),
        "case_openings_chart": {"items": [{"case_id": 1, "name": "WALLZ CS2 Case", "image_url": "", "openings": 248, "unique_openers": 183, "width": 100, "prize_drops": []}, {"case_id": 2, "name": "Cyber Bonus Case", "image_url": "", "openings": 164, "unique_openers": 129, "width": 66, "prize_drops": []}], "total_openings": 412, "unique_openers": 274, "period_days": period},
        "mission_completions_chart": {"items": [{"mission_id": 1, "name": "Флеш-рояль", "completions": 129, "width": 100}, {"mission_id": 2, "name": "Кофейный энтузиаст", "completions": 88, "width": 68}, {"mission_id": 3, "name": "Ночная лига", "completions": 61, "width": 47}], "total_completions": 278, "period_days": period},
        "first_visit_feedback": {"avg_rating": 4.6, "avg_rating_display": "4,6", "total_responses": 86, "positive_count": 64, "negative_count": 22, "positive_preview": positive, "negative_preview": negative, "positive_messages": positive, "negative_messages": negative, "period_days": period},
    }


def _analysis() -> dict:
    counts = [3830, 1822, 1307, 1046, 880, 761, 672]
    return {
        "audience": {"total": 4377, "telegram": 3115, "telegram_percent": 71.2},
        "funnel": [{"step": i, "label": f"{i} визит", "count": count, "height": round(count / counts[0] * 100), "gap_to_next": [40.8, 35.3, 29.3, 27.2, 24.3, 20.7, None][i - 1]} for i, count in enumerate(counts, 1)],
        "funnel_period_label": "за всё время",
        "metrics": [{"label": "Среднее пополнение", "value": "411 ₽", "hint": "По пополнениям за последние 30 дней"}, {"label": "Средняя длина визита", "value": "3 ч 29 мин", "hint": "Сессии с разрывом до 2 часов склеиваются"}, {"label": "Визитов в месяц", "value": "0.6", "hint": "Среднее число визитов на гостя"}, {"label": "Ночь / день", "value": "27.8% / 72.2%", "hint": "Доля ночных и дневных визитов"}, {"label": "Выходные / будни", "value": "32.4% / 67.6%", "hint": "Доля визитов по дням недели"}],
    }


def _crm_context(section: str = "cohorts") -> dict:
    period = request.args.get("period", 30, type=int)
    if period not in (7, 30, 90):
        period = 30
    date_from, date_to = _demo_date_range(period)
    period = (date_to - date_from).days + 1
    hours = list(range(24))
    days = [("Пн", "Понедельник"), ("Вт", "Вторник"), ("Ср", "Среда"), ("Чт", "Четверг"), ("Пт", "Пятница"), ("Сб", "Суббота"), ("Вс", "Воскресенье")]
    grid = []
    for day_index, (label, full) in enumerate(days):
        cells = []
        for hour in hours:
            value = max(0, min(96, int(12 + 54 * (1 - abs(hour - 20) / 13) + day_index * 3)))
            cells.append({"hour": hour, "value": value, "level": min(5, max(1, value // 20 + 1))})
        grid.append({"day": {"label": label, "full": full}, "cells": cells})
    pcs = []
    for index in range(1, 31):
        utilization = round(12 + (index * 17) % 72 + (index % 3) * .4, 1)
        hours_value = round(utilization * period * 24 / 100, 1)
        pcs.append({"uuid": f"demo-pc-{index}", "name": f"ПК {index}", "display_name": f"ПК {index}", "hours": hours_value, "hours_display": str(hours_value).replace(".", ","), "sessions_count": 10 + index * 2, "utilization_percent": utilization, "utilization_display": str(utilization).replace(".", ","), "level": min(5, max(1, int(utilization // 20 + 1)))})
    return {
        **_common(section), "analytics_section": section, "selected_period": period, "telegram_only": False,
        "selected_date_from": date_from.isoformat(),
        "selected_date_to": date_to.isoformat(),
        "selected_period_label": f"{date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
        "heatmap_max_date": datetime.now().date().isoformat(),
        "audience": {"total": 4377, "telegram": 3115}, "heatmap": {"hours": hours, "grid": grid, "utilization_display": "36,8", "peak": {"day": "Суббота", "hour": "21:00", "value": 91}},
        "pc_heatmap": {"pcs": pcs, "total_hours_display": "4 910,2", "utilization_display": "26,2", "peak": max(pcs, key=lambda item: item["utilization_percent"])},
        "filter_fields": _filter_fields(), "message_variables": _message_variables(),
        "cohorts": [{"id": 1, "name": "3+ визитов ночью", "rules_json": {"rules": [{"field": "visits_total", "operator": "gte", "value": 3}]}}, {"id": 2, "name": "Новые гости", "rules_json": {"rules": []}}],
        "initial_analysis": _analysis(), "manual_campaigns": [], "crm_pulse_groups": [],
    }


def _missions() -> list[dict]:
    now = datetime.now()
    return [
        {"id": 1, "name": "DONKED", "display_name": "DONKED", "description": "Открой CS2 WALLZ Case 5 раз", "target_metric": "case_openings_count", "target_value": 5, "target": 5, "reward_tokens": 3, "reward_bonus": 150, "reward_text": "+3 жет. · +150 КБ", "is_active": 1, "starts_at": now - timedelta(days=10), "ends_at": now + timedelta(days=20), "case_id": 1},
        {"id": 2, "name": "Флеш-рояль", "display_name": "Флеш-рояль", "description": "Посети клуб 5 дней подряд", "target_metric": "visit_streak_days", "target_value": 5, "target": 5, "reward_tokens": 10, "reward_bonus": 0, "reward_text": "+10 жет.", "is_active": 1, "starts_at": now - timedelta(days=4), "ends_at": now + timedelta(days=26), "case_id": None},
        {"id": 3, "name": "Ночная лига", "display_name": "Ночная лига", "description": "Посети клуб 4 раза ночью", "target_metric": "night_visits", "target_value": 4, "target": 4, "reward_tokens": 5, "reward_bonus": 0, "reward_text": "+5 жет.", "is_active": 1, "starts_at": now + timedelta(days=5), "ends_at": now + timedelta(days=35), "case_id": None},
    ]


def _settings_context(defaults: dict) -> dict:
    tab = request.args.get("tab") or defaults.get("tab", "club")
    editor = request.args.get("editor") or defaults.get("editor", "wheel")
    club = {"name": "DEMO CLUB", "timezone": "Europe/Moscow", "lg_api_key": "demo-key", "secret": "demo-secret", "cm_bonus_admin_chat_id": "-1000000000000", "instagram_url": "https://instagram.com/demo", "youtube_url": "https://youtube.com/@demo", "vk_url": "https://vk.com/demo", "telegram_channel_url": "https://t.me/demo", "yandex_maps_url": "", "two_gis_url": ""}
    return {
        **_common("settings"), "active_tab": tab, "bonus_editor": editor, "club": club,
        "guest_login_url": flask_url_for("demo.guest", _external=True), "timezone_choices": [("Europe/Moscow", "Москва (UTC+3)"), ("Asia/Yekaterinburg", "Екатеринбург (UTC+5)")], "club_timezone_label": "Москва (UTC+3)",
        "pc_name_settings": [{"uuid": f"demo-pc-{i}", "display_name": f"ПК {i}"} for i in range(1, 13)],
        "system_status": {"timezone_label": "Время клуба: Москва", "updates": [], "auto_mailings": []},
        "templates": [], "missions": _missions(), "active_cases": DEMO_CASES,
        "contract_feature_settings": {"is_enabled": True}, "contract_reward_settings": {key: {"tokens": value[0], "bonus": value[1]} for key, value in {"easy": (1, 50), "medium": (2, 100), "hard": (3, 200)}.items()},
        "wheel_settings": {"tokens_start_date": datetime.now() - timedelta(days=90), "spin_cost": 2, "is_enabled": 1, "show_only_own_valuable_drops": 0},
        "prizes": [], "wheel_active_prob_sum": 100, "prize_icon_choices": ["🎮", "🏆", "🥤", "🔥", "💎", "🪙"], "game_mode": "cases", "cases": DEMO_CASES,
        "case_upload_usage": {"used_mb": 1.7, "limit_mb": 25, "remaining_mb": 23.3, "percent": 6.8},
        "topup_bonus_settings": {"is_enabled": 1, "rules": [{"amount": 1000, "bonus": 300}], "message_template": "Вам начислено {bonus_amount} КБ"},
        "welcome_reward_settings": {"welcome_reward_enabled": 1, "welcome_cm_bonus_amount": 100, "welcome_token_amount": 3},
        "topup_bonus_variables": [], "topup_bonus_exclude_from_amount": 100000, "topup_bonus_max_rule_amount": 99999.99,
        "guest_management_phone": request.args.get("phone", ""), "guest_lookup": None, "drop_phone": request.args.get("phone", ""), "drop_request_key": "demo", "drop_page": {"guests": [], "targets": [], "history": [], "total": 0, "show_all": False, "page": 1, "pages": 1},
        "profile_user": {"name": "Демо-пользователь", "login": "demo", "email": "demo@cyber-bonus.ru"},
    }


def _mailing_context() -> dict:
    return {
        **_common("mailing"), "filter_fields": _filter_fields(), "message_variables": _message_variables(),
        "crm_segments": [{"key": "active", "emoji": "🔥", "title": "Активные", "description": "Недавно были в клубе", "rules": []}, {"key": "risk", "emoji": "💤", "title": "В зоне риска", "description": "Давно не возвращались", "rules": []}],
        "segments": [{"id": 1, "name": "Ночные гости", "rules_json": {"rules": []}}, {"id": 2, "name": "VIP", "rules_json": {"rules": []}}],
        "mailings": [], "auto_mailings": [], "club_timezone_label": "Москва (UTC+3)", "bonus_giveaways": [], "crm_interactions": [],
    }


def _guest_context() -> dict:
    session.setdefault("demo_guest_tokens", 24)
    session.setdefault("demo_guest_bonus", 350)
    return {
        **_common("guest"), "session": {}, "guest_name": "Алексей", "guest_id": 1001,
        "profile_stats": {"total_minutes": 8920, "total_hours": 148, "loyalty_level_placeholder": "Gold", "bonus_balance_placeholder": 350},
        "wheel_settings": {"spin_cost": 2, "is_enabled": 1}, "wheel_prizes": [], "game_mode": "cases", "cases": DEMO_CASES,
        "valuable_case_drops": [], "valuable_drops_duration": 90, "token_balance": int(session["demo_guest_tokens"]), "reward_history": [],
        "streak_info": {"current_streak": 5, "best_streak": 12}, "cm_bonus_balance": int(session["demo_guest_bonus"]), "cm_bonus_history": [], "cm_bonus_redeem_history": [],
        "steam_account": None, "game_contracts_enabled": False, "game_contracts_state": {"steam_linked": False, "games": {}}, "contracts_state": {},
        "guest_missions": [{"id": 1, "name": "Флеш-рояль", "description": "Посети клуб 5 дней подряд", "progress": 3, "target": 5, "progress_percent": 60, "is_completed": False, "reward_display": "+10 жет."}, {"id": 2, "name": "Кофейный энтузиаст", "description": "Купи 5 напитков", "progress": 5, "target": 5, "progress_percent": 100, "is_completed": True, "reward_display": "+50 КБ"}],
    }


@demo_bp.get("")
@demo_bp.get("/")
def index():
    return render_template("owner/dashboard.html", **_dashboard_context())


@demo_bp.get("/guest")
def guest():
    return render_template("guest/guest_dashboard.html", **_guest_context())


@demo_bp.get("/<page>")
def owner_page(page: str):
    config = PAGE_MAP.get(page)
    if not config:
        return render_template("demo/not_found.html"), 404
    template, kind, defaults = config
    if kind == "dashboard": context = _dashboard_context()
    elif kind == "crm": context = _crm_context(defaults.get("analytics_section", page))
    elif kind == "pulse": context = {**_common("guest-pulse"), "segments": {"active": "Активные", "risk": "В зоне риска", "lost": "Потерянные"}, "message_variables": _message_variables(), "outbound_disabled": False}
    elif kind == "team": context = _common("team")
    elif kind == "mailing": context = _mailing_context()
    elif kind == "training": context = {**_common("training"), "videos": []}
    else: context = _settings_context(defaults)
    context["demo_page"] = page
    return render_template(template, **context)


@demo_bp.route("/action/<path:action>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def action(action: str):
    return jsonify({"ok": True, "demo": True, "message": "Изменение сохранено только в демо-режиме"})


def _team_payload() -> dict:
    today = datetime.now().date()
    admins = []
    for index, name in enumerate(["Анна Орлова", "Максим Волков", "Илья Соколов", "Мария Лебедева"], 1):
        club_regs, connected = 54 - index * 7, 46 - index * 7
        visit2, visit3 = round(club_regs * (0.72 - index * .04)), round(club_regs * (0.72 - index * .04) * (0.68 - index * .03))
        admins.append({"admin_id": index, "name": name, "work_schedule": "night" if index % 2 == 0 else "day", "has_recent_shift": True, "is_working": True, "club_registrations": club_regs, "club_to_module": connected, "module_registrations": connected + 4, "module_estimated": 0, "shift_count": 11 - index, "module_conversion": round(connected / club_regs * 100, 1), "cohort": club_regs, "visit1": club_regs, "visit2": visit2, "visit3": visit3, "conversion12": round(visit2 / club_regs * 100, 1), "conversion23": round(visit3 / visit2 * 100, 1)})
    return {"ok": True, "today": today.isoformat(), "registration_range": [(today - timedelta(days=29)).isoformat(), today.isoformat()], "updated_at": datetime.now().isoformat(timespec="minutes"), "timezone": "Москва (UTC+3)", "stale": False, "admins": admins}


def _guest_rows() -> list[dict]:
    rows = []
    for index, name in enumerate(["Терентьев Пётр Александрович", "Никушин Максим Александрович", "Сергеева Виктория Борисовна", "Мещеряков Алексей Михайлович", "Хусаинов Бекбулат Бержанович"], 1):
        health, value, engagement = 48 + index * 7, round(43 + index * 6.4, 1), 20 + index * 8
        rows.append({"guest_id": index, "name": name, "phone": f"+7 999 000 0{index:03d}", "lifecycle_label": ["Потерянный", "Активный", "Лояльный"][index % 3], "has_telegram": index != 4, "health": {"score": health}, "value": {"score": value}, "engagement": {"score": engagement}, "overall": {"score": round(health * .35 + value * .4 + engagement * .25, 1), "label": "Средний"}})
    return rows


@demo_bp.route("/api/owner/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def owner_api(path: str):
    if path == "team": return jsonify(_team_payload())
    if path == "team/admins": return jsonify({"ok": True})
    if path == "dashboard/engagement":
        return jsonify({"ok": True, "data": _dashboard_context()["engagement_all_time_data"]})
    if path == "dashboard/case-openings-timeline":
        return jsonify({"ok": True, "cases": [{"id": 1, "name": "WALLZ CS2 Case", "color": "#8f5bff"}, {"id": 2, "name": "Cyber Bonus Case", "color": "#3fc9f2"}], "buckets": [{"label": f"{day:02d}.09", "values": [10 + (day * 7) % 26, 6 + (day * 5) % 18]} for day in range(1, 15)], "group_by": "day", "max_value": 36})
    if path == "crm-analysis/preview": return jsonify({"ok": True, "analysis": _analysis()})
    if path == "crm-auto-campaigns":
        date_from, date_to = _demo_date_range(7)
        campaigns = [
            {"code": "guest_return", "title": "Возвращение гостя", "unique_recipients": 184, "returned_count": 51, "conversion_percent": 27.7, "topped_up_count": 36, "topup_amount": 48200},
            {"code": "first_visit", "title": "После первого визита", "unique_recipients": 96, "returned_count": 34, "conversion_percent": 35.4, "topped_up_count": 21, "topup_amount": 26700},
        ]
        return jsonify({"ok": True, "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "campaigns": campaigns})
    if path.startswith("crm-cohorts"): return jsonify({"ok": True, "id": random.randint(10, 99)})
    if path == "guest-pulse":
        rows = _guest_rows()
        audiences = [{"key": "active", "label": "Активные", "color": "#65e7ad", "count": 182, "telegram_count": 149, "without_telegram_count": 33}, {"key": "loyal", "label": "Лояльные", "color": "#9d6cff", "count": 141, "telegram_count": 118, "without_telegram_count": 23}, {"key": "risk", "label": "В зоне риска", "color": "#ff9e64", "count": 76, "telegram_count": 54, "without_telegram_count": 22}, {"key": "lost", "label": "Потерянные", "color": "#ff708f", "count": 38, "telegram_count": 25, "without_telegram_count": 13}]
        deviations = []
        for row in rows[:4]:
            copy = dict(row); copy["deviations"] = [{"metric": "health", "baseline_30d": row["health"]["score"] + 18, "score": row["health"]["score"], "deviation_points": -18, "deviation_percent": -28.4, "deviation_direction": "DOWN", "deviation_ratio": .284, "baseline_estimated": False}]; deviations.append(copy)
        return jsonify({"ok": True, "calculated_at": datetime.now().isoformat(timespec="minutes"), "stale": False, "total": 437, "audiences": audiences, "selected_count": 437, "selected_telegram_count": 346, "selected_without_telegram_count": 91, "guests": rows, "deviation_count": len(deviations), "deviation_telegram_count": 3, "deviations": deviations, "page_size": 10})
    if path.startswith("guest-pulse/guests/"):
        guest_id = int(path.rsplit("/", 1)[-1]); row = next((item for item in _guest_rows() if item["guest_id"] == guest_id), _guest_rows()[0])
        guest = {**row, "health": {"score": row["health"]["score"], "delta_14d": -8, "preliminary": False, "recency": 61, "frequency": 72, "trend": 48, "consistency": 66, "score_7d_ago": 64, "score_14d_ago": 71, "score_30d_ago": 76, "reason_text": "Обычно приходит раз в 4 дня. Последний визит был 11 дней назад."}, "value": {"score": row["value"]["score"], "revenue_90d": 6200, "played_hours_90d": 54, "visits_90d": 12, "avg_check_90d": 517, "percentiles": {"revenue_90d": 68, "played_hours_90d": 71, "visits_90d": 65, "avg_check_90d": 59}, "reference_count": 437}, "engagement": {"score": row["engagement"]["score"], "missions_completed_30d": 3, "contracts_selected_30d": 2, "contracts_completed_30d": 1, "cb_actions_30d": 9, "current_streak": 4, "last_cb_activity_at": datetime.now().isoformat(timespec="minutes")}, "visits": {"last_visit_date": (datetime.now() - timedelta(days=11)).isoformat(timespec="minutes"), "typical_gap_days": 4.1, "visits_total": 38}, "visit_pattern": {"period": "День", "calendar": "Будни", "night_share": 44.0, "weekend_share": 31.5}, "games": {"favorite_game": "cs2", "favorite_game_hours": 219, "recent_game_14d": "cs2", "recent_game_14d_hours": 31, "updated_at": datetime.now().isoformat(timespec="minutes")}}
        history = [{"snapshot_date": (datetime.now() - timedelta(days=i)).date().isoformat(), "health_score": 61 + i % 6, "value_score": 68, "engagement_score": 52 + i % 4, "reconstructed": False} for i in range(10)]
        return jsonify({"ok": True, "guest": guest, "history": history, "events": []})
    if path.startswith("guest-pulse/selection"): return jsonify({"ok": True, "group": {"key": "demo", "title": "Демо-аудитория", "guest_ids": [1, 2, 3], "guests": _guest_rows()[:3], "total_count": 3}})
    if path.startswith("segments/preview"): return jsonify({"ok": True, "count": 346, "sample": []})
    return jsonify({"ok": True, "demo": True, "message": "Действие выполнено в демо-режиме"})


@demo_bp.route("/api/guest/<path:path>", methods=["GET", "POST"])
def guest_api(path: str):
    if path == "tokens": return jsonify({"ok": True, "tokens": int(session.get("demo_guest_tokens", 24)), "spin_cost": 2, "is_enabled": True})
    if path == "cm-bonuses": return jsonify({"ok": True, "balance": int(session.get("demo_guest_bonus", 350))})
    if path == "cm-bonuses/redeem":
        amount = int(session.get("demo_guest_bonus", 350)); session["demo_guest_bonus"] = 0
        return jsonify({"ok": True, "amount": amount, "balance_after": 0})
    if path.startswith("cases/") and path.endswith("/open"):
        try: case_id = int(path.split("/")[1])
        except (ValueError, IndexError): return jsonify({"error": "case_not_found"}), 404
        return _open_case(case_id)
    return jsonify({"ok": True, "demo": True})


@demo_bp.post("/guest/cases/<int:case_id>/open")
def guest_case_open(case_id: int):
    return _open_case(case_id)


@demo_bp.post("/guest/reset")
def guest_reset():
    session["demo_guest_tokens"] = 24
    session["demo_guest_bonus"] = 350
    return jsonify({"ok": True, "tokens": 24, "balance": 350})


def _open_case(case_id: int):
    case = next((item for item in DEMO_CASES if item["id"] == case_id), None)
    if not case: return jsonify({"error": "case_not_found"}), 404
    balance, price = int(session.get("demo_guest_tokens", 24)), int(case["price_tokens"])
    if balance < price: return jsonify({"error": "no_tokens", "tokens_after": balance}), 400
    items = [item for item in case["items"] if item["is_active"]]
    item = random.choices(items, weights=[entry["probability"] for entry in items], k=1)[0]
    balance = balance - price + int(item.get("token_amount") or 0); session["demo_guest_tokens"] = balance
    session["demo_guest_bonus"] = int(session.get("demo_guest_bonus", 350)) + int(item.get("bonus_amount") or 0)
    claim = None if item.get("bonus_amount") or item.get("token_amount") else {"id": random.randint(1000, 9999), "status": "pending", "status_label": "ожидает выдачи"}
    return jsonify({"ok": True, "item": item, "claim": claim, "tokens_after": balance})
