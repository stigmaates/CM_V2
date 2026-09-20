from __future__ import annotations

import random
from datetime import datetime

from flask import Blueprint, jsonify, render_template, session


demo_bp = Blueprint("demo", __name__, url_prefix="/demo")


DEMO_PAGES = {
    "overview": ("Обзор", "Главные показатели демонстрационного клуба", "overview"),
    "cases": ("Кейсы и колесо фортуны", "Настройка игровых механик и призов", "cases"),
    "missions": ("Задания", "Активные, запланированные и завершённые задания", "missions"),
    "contracts": ("Контракты", "Игровые контракты для гостей клуба", "cards"),
    "promotions": ("Акции", "Предложения и бонусные кампании", "cards"),
    "managed-drops": ("Управляемое выпадение", "Персональные призы и сценарии выдачи", "table"),
    "mailings": ("Рассылки и авторассылки", "Коммуникации с гостями", "communications"),
    "guest-pulse": ("Пульс гостя", "Состояние и поведение гостевой базы", "guests"),
    "cohorts": ("Анализ по когортам", "Возвраты и ценность выбранной аудитории", "cohorts"),
    "communications": ("Анализ коммуникаций", "Результаты отправленных кампаний", "communications"),
    "heatmaps": ("Тепловые карты", "Загрузка клуба по времени и компьютерам", "heatmaps"),
    "team": ("Команда", "Сотрудники и показатели смен", "team"),
    "settings": ("Настройки клуба", "Параметры демонстрационного клуба", "settings"),
    "guests": ("Управление гостями", "Баланс, доступ и статусы гостей", "guests"),
    "training": ("Обучение", "Короткие инструкции по работе с модулем", "training"),
}


DEMO_CASES = [
    {
        "id": 1,
        "name": "Cyber Starter",
        "description": "Бонусы, жетоны и небольшие игровые призы.",
        "price": 2,
        "badge": "Базовый",
        "color": "#5aa9ff",
        "symbol": "◈",
        "items": [
            {"name": "+50 КБ", "description": "Начислено на демо-баланс", "symbol": "₽", "weight": 34},
            {"name": "+2 жетона", "description": "Можно открыть ещё один кейс", "symbol": "●", "weight": 28, "tokens": 2},
            {"name": "Напиток", "description": "Демо-заявка на выдачу", "symbol": "◆", "weight": 24},
            {"name": "Час игры", "description": "Демо-заявка на выдачу", "symbol": "⌁", "weight": 14},
        ],
    },
    {
        "id": 2,
        "name": "Night Shift",
        "description": "Призы для ночных гостей и постоянных игроков.",
        "price": 4,
        "badge": "Редкий",
        "color": "#a66cff",
        "symbol": "☾",
        "items": [
            {"name": "+150 КБ", "description": "Начислено на демо-баланс", "symbol": "₽", "weight": 36},
            {"name": "+5 жетонов", "description": "Жетоны вернулись на баланс", "symbol": "●", "weight": 22, "tokens": 5},
            {"name": "3 часа игры", "description": "Демо-заявка на выдачу", "symbol": "⌁", "weight": 28},
            {"name": "Мерч клуба", "description": "Редкий демонстрационный приз", "symbol": "★", "weight": 14},
        ],
    },
    {
        "id": 3,
        "name": "Legendary Drop",
        "description": "Крупные награды для демонстрации механики.",
        "price": 7,
        "badge": "Легендарный",
        "color": "#ffd35a",
        "symbol": "✦",
        "items": [
            {"name": "+500 КБ", "description": "Начислено на демо-баланс", "symbol": "₽", "weight": 44},
            {"name": "+10 жетонов", "description": "Большой возврат жетонов", "symbol": "●", "weight": 20, "tokens": 10},
            {"name": "Ночь в клубе", "description": "Демо-заявка на выдачу", "symbol": "☾", "weight": 25},
            {"name": "Игровая мышь", "description": "Главный демонстрационный приз", "symbol": "♛", "weight": 11},
        ],
    },
]


def _random_rows(count: int = 8) -> list[dict]:
    first_names = ["Александр", "Мария", "Максим", "Артём", "Екатерина", "Илья", "Виктория", "Даниил"]
    last_names = ["Соколов", "Иванова", "Морозов", "Волков", "Орлова", "Попов", "Лебедева", "Кузнецов"]
    statuses = ["Активный", "Лояльный", "Новый", "В зоне риска"]
    rows = []
    for index in range(count):
        visits = random.randint(2, 28)
        value = round(random.uniform(18, 98), 1)
        engagement = random.randint(10, 96)
        rows.append(
            {
                "id": 10_000 + random.randint(1, 89_999),
                "name": f"{first_names[index % len(first_names)]} {last_names[index % len(last_names)]}",
                "status": random.choice(statuses),
                "visits": visits,
                "value": value,
                "engagement": engagement,
                "score": round(visits * 0.35 + value * 0.4 + engagement * 0.25, 1),
            }
        )
    return rows


def _demo_context(page: str) -> dict:
    title, subtitle, kind = DEMO_PAGES[page]
    guests = random.randint(280, 620)
    return {
        "page": page,
        "title": title,
        "subtitle": subtitle,
        "kind": kind,
        "cards": [
            {"label": "Гостей", "value": f"{guests:,}".replace(",", " "), "change": f"+{random.randint(4, 18)}%", "icon": "users"},
            {"label": "Посещений", "value": f"{random.randint(900, 1900):,}".replace(",", " "), "change": f"+{random.randint(3, 14)}%", "icon": "calendar"},
            {"label": "Средний чек", "value": f"{random.randint(480, 890)} ₽", "change": f"+{random.randint(2, 11)}%", "icon": "wallet"},
            {"label": "Возвращаются", "value": f"{random.randint(54, 82)}%", "change": f"+{random.randint(1, 8)}%", "icon": "return"},
        ],
        "rows": _random_rows(),
        "chart": [random.randint(32, 96) for _ in range(14)],
        "hours": [random.randint(12, 86) for _ in range(24)],
        "pc_load": [random.randint(8, 96) for _ in range(30)],
        "cases": DEMO_CASES,
        "now": datetime.now(),
    }


@demo_bp.get("")
@demo_bp.get("/")
def index():
    return render_template("demo/owner.html", **_demo_context("overview"))


@demo_bp.get("/guest")
def guest():
    session.setdefault("demo_guest_tokens", 24)
    session.setdefault("demo_guest_history", [])
    return render_template(
        "demo/guest.html",
        cases=DEMO_CASES,
        token_balance=int(session["demo_guest_tokens"]),
        history=session["demo_guest_history"],
    )


@demo_bp.post("/guest/reset")
def guest_reset():
    session["demo_guest_tokens"] = 24
    session["demo_guest_history"] = []
    return jsonify({"ok": True, "tokens": 24})


@demo_bp.post("/guest/cases/<int:case_id>/open")
def guest_case_open(case_id: int):
    case = next((item for item in DEMO_CASES if item["id"] == case_id), None)
    if case is None:
        return jsonify({"ok": False, "error": "case_not_found"}), 404

    balance = int(session.get("demo_guest_tokens", 24))
    price = int(case["price"])
    if balance < price:
        return jsonify({"ok": False, "error": "no_tokens", "tokens": balance}), 400

    prizes = case["items"]
    prize = random.choices(prizes, weights=[item["weight"] for item in prizes], k=1)[0]
    balance = balance - price + int(prize.get("tokens", 0))
    session["demo_guest_tokens"] = balance
    history = list(session.get("demo_guest_history") or [])
    history.insert(
        0,
        {
            "case": case["name"],
            "name": prize["name"],
            "symbol": prize["symbol"],
            "time": datetime.now().strftime("%H:%M"),
        },
    )
    session["demo_guest_history"] = history[:8]
    return jsonify({"ok": True, "tokens": balance, "prize": prize, "history": history[:8]})


@demo_bp.get("/<page>")
def page(page: str):
    if page not in DEMO_PAGES:
        return render_template("demo/not_found.html"), 404
    return render_template("demo/owner.html", **_demo_context(page))
