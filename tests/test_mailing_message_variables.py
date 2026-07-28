from decimal import Decimal

from app.services.mailing import render_message_template


def test_render_message_template_replaces_guest_metrics():
    text = "{first_name}, привет! У тебя {sessions_30d} сессий, {cm_bonus_balance} КБ и {token_balance} жет."
    recipient = {
        "fio": "Дмитрий Антонович Морозов",
        "sessions_30d": 7,
        "cm_bonus_balance": Decimal("150.00"),
        "token_balance": 3,
    }

    assert render_message_template(text, recipient) == "Дмитрий, привет! У тебя 7 сессий, 150 КБ и 3 жет."


def test_render_message_template_keeps_unknown_variables():
    assert render_message_template("Привет, {club_name}", {}) == "Привет, {club_name}"
