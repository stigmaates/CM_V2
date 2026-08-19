from decimal import Decimal

import pytest

from app.services.topup_bonuses import (
    render_topup_bonus_message,
    save_topup_bonus_settings,
    select_topup_bonus_rule,
)


def test_select_topup_bonus_rule_uses_highest_matching_threshold():
    rules = [
        {"id": 1, "min_amount": Decimal("500.00"), "bonus_amount": 50},
        {"id": 2, "min_amount": Decimal("1000.00"), "bonus_amount": 150},
        {"id": 3, "min_amount": Decimal("2000.00"), "bonus_amount": 400},
    ]

    assert select_topup_bonus_rule(rules, Decimal("1500.00"))["id"] == 2


def test_select_topup_bonus_rule_returns_none_below_first_threshold():
    rules = [{"id": 1, "min_amount": Decimal("500.00"), "bonus_amount": 50}]

    assert select_topup_bonus_rule(rules, Decimal("499.99")) is None


def test_render_topup_bonus_message_replaces_supported_variables():
    message = render_topup_bonus_message(
        (
            "{first_name}, пополнение {topup_amount} в {club_name}. "
            "Порог {min_sum}, начислено {bonus_amount}, баланс {cm_bonus_balance}."
        ),
        {
            "fio": "Морозов Дмитрий Антонович",
            "club_name": "WALLZ",
            "topup_amount": Decimal("1250.50"),
            "min_amount": Decimal("1000.00"),
            "bonus_amount": 300,
            "cm_bonus_balance": 740,
        },
    )

    assert message == "Дмитрий, пополнение 1250.5 в WALLZ. Порог 1000, начислено 300, баланс 740."


def test_render_topup_bonus_message_preserves_unknown_variable():
    assert render_topup_bonus_message("Тест {unknown}", {}) == "Тест {unknown}"


def test_render_topup_bonus_message_extracts_first_name_from_female_fio():
    assert render_topup_bonus_message("Привет, {first_name}", {"fio": "Петрова Анна Сергеевна"}) == "Привет, Анна"


def test_topup_bonus_rule_rejects_excluded_amount_boundary():
    with pytest.raises(ValueError, match="меньше 30000"):
        save_topup_bonus_settings(
            1,
            is_enabled=True,
            message_template="Тест",
            rules=[{"min_amount": 30000, "bonus_amount": 500}],
        )
