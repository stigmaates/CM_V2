import re
from decimal import Decimal

import app.services.mailing as mailing_service
from app.services.mailing import build_where_clause, render_message_template
from scripts.process_auto_mailings import _format_streak_reminder_message


def test_render_message_template_replaces_guest_metrics():
    text = (
        "{first_name}, привет! У тебя {sessions_30d} сессий, {cm_bonus_balance} КБ, "
        "{token_balance} жет. и {case_openings_count} открытий кейсов."
    )
    recipient = {
        "fio": "Дмитрий Антонович Морозов",
        "sessions_30d": 7,
        "cm_bonus_balance": Decimal("150.00"),
        "token_balance": 3,
        "case_openings_count": 4,
    }

    assert (
        render_message_template(text, recipient)
        == "Дмитрий, привет! У тебя 7 сессий, 150 КБ, 3 жет. и 4 открытий кейсов."
    )


def test_render_message_template_detects_first_name_in_surname_first_fio():
    assert render_message_template("Привет, {first_name}!", {"fio": "Морозов Дмитрий Антонович"}) == "Привет, Дмитрий!"


def test_render_message_template_replaces_club_name_and_keeps_unknown_variables():
    assert (
        render_message_template("Привет из {club_name}, {unknown_var}", {"club_name": "WALLZ"})
        == "Привет из WALLZ, {unknown_var}"
    )


def test_streak_reminder_template_replaces_common_and_streak_variables():
    template = (
        "Привет, {first_name}! У тебя в {club_name} стрик из дней — {streak_days}.\n"
        "Приди еще раз до {date} и получи {next_reward} жетонов."
    )
    candidate = {
        "fio": "Морозов Дмитрий Антонович",
        "club_name": "WALLZ",
        "streak_days": 4,
        "cycle_end": "2026-08-14",
        "next_reward": 5,
    }

    assert (
        _format_streak_reminder_message(template, candidate)
        == "Привет, Дмитрий! У тебя в WALLZ стрик из дней — 4.\nПриди еще раз до 2026-08-14 и получи 5 жетонов."
    )


def test_mailing_recipients_require_real_telegram_id_not_cached_portrait_flag():
    where_sql, params = build_where_clause(1, [])

    assert "g.telegram_id IS NOT NULL" in where_sql
    assert "up.has_telegram = 1" not in where_sql
    assert params == [1]


def test_case_openings_count_is_available_as_number_filter():
    field = mailing_service.FILTER_FIELDS["case_openings_count"]

    assert field["type"] == "number"
    assert field["label"] == "Количество открытий кейсов"
    assert "guest_case_openings" in field["column"]


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
    assert not any("только для раздачи КБ" in value for value in constants)


def test_bonus_giveaway_expiring_supports_token_transactions():
    constants = [value for value in mailing_service.create_bonus_giveaway.__code__.co_consts if isinstance(value, str)]

    assert any("token_amount" in value for value in constants)
    assert any("Раздача жетонов" in value for value in constants)
    assert any("expires_at" in value and "token_transaction_status" in value for value in constants)


def test_auto_mailings_support_editable_delay_and_message_templates():
    ensure_constants = [
        value for value in mailing_service.ensure_auto_mailings.__code__.co_consts if isinstance(value, str)
    ]
    update_constants = [
        value for value in mailing_service.update_auto_mailing_settings.__code__.co_consts if isinstance(value, str)
    ]

    assert any("delay_minutes" in value for value in ensure_constants)
    assert any("message_text = %s" in value for value in update_constants)
    assert any("title = %s" in value for value in update_constants)
    assert any("description = %s" in value for value in update_constants)
