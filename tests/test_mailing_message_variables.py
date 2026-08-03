import re
from decimal import Decimal

import app.services.mailing as mailing_service
from app.services.mailing import build_where_clause, render_message_template


def test_render_message_template_replaces_guest_metrics():
    text = "{first_name}, привет! У тебя {sessions_30d} сессий, {cm_bonus_balance} КБ и {token_balance} жет."
    recipient = {
        "fio": "Дмитрий Антонович Морозов",
        "sessions_30d": 7,
        "cm_bonus_balance": Decimal("150.00"),
        "token_balance": 3,
    }

    assert render_message_template(text, recipient) == "Дмитрий, привет! У тебя 7 сессий, 150 КБ и 3 жет."


def test_render_message_template_detects_first_name_in_surname_first_fio():
    assert render_message_template("Привет, {first_name}!", {"fio": "Морозов Дмитрий Антонович"}) == "Привет, Дмитрий!"


def test_render_message_template_keeps_unknown_variables():
    assert render_message_template("Привет, {club_name}", {}) == "Привет, {club_name}"


def test_mailing_recipients_require_real_telegram_id_not_cached_portrait_flag():
    where_sql, params = build_where_clause(1, [])

    assert "g.telegram_id IS NOT NULL" in where_sql
    assert "up.has_telegram = 1" not in where_sql
    assert params == [1]


def test_bonus_giveaway_recipient_insert_has_placeholder_for_token_error_text():
    source = mailing_service.create_bonus_giveaway.__code__.co_consts
    sql = next(value for value in source if isinstance(value, str) and "INSERT INTO bonus_giveaway_recipients" in value)

    columns_part = sql.split("(", 1)[1].split(")", 1)[0]
    values_part = sql.split("VALUES", 1)[1]
    columns_count = len([line for line in columns_part.splitlines() if line.strip().rstrip(",")])

    assert "token_error_text" in columns_part
    assert len(re.findall(r"%s", values_part)) == columns_count + 1


def test_bonus_giveaway_supports_expiring_bonus_columns():
    constants = [value for value in mailing_service.create_bonus_giveaway.__code__.co_consts if isinstance(value, str)]

    assert any("is_expiring" in value for value in constants)
    assert any("expires_after_seconds" in value for value in constants)
    assert any("expires_at" in value for value in constants)
