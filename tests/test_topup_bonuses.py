from datetime import datetime
from decimal import Decimal

import pytest

from app.services.topup_bonuses import (
    TOPUP_BONUS_DUPLICATE_WINDOW,
    _claim_topup_bonus_award,
    _resolve_enabled_at,
    award_first_authorization_reward,
    render_topup_bonus_message,
    save_topup_bonus_settings,
    save_welcome_reward_settings,
    select_topup_bonus_rule,
)


class _TopupClaimCursor:
    def __init__(self, duplicate_award=None, insert_rowcount=1):
        self.duplicate_award = duplicate_award
        self.insert_rowcount = insert_rowcount
        self.rowcount = 0
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if "INSERT IGNORE INTO guest_topup_bonus_awards" in query:
            self.rowcount = self.insert_rowcount

    def fetchone(self):
        return self.duplicate_award


def _claim_topup(cursor):
    return _claim_topup_bonus_award(
        cursor,
        club_id=2,
        topup={
            "topup_id": 699621,
            "guest_id": 15173,
            "amount": Decimal("1500.00"),
            "topup_at": datetime(2026, 8, 27, 10, 32, 25),
            "telegram_id": 123,
        },
        rule={"id": 7, "bonus_amount": 300, "reward_type": "cm_bonus"},
        awarded_at=datetime(2026, 8, 27, 10, 33, 6),
    )


def test_topup_bonus_duplicate_window_is_one_hour():
    assert TOPUP_BONUS_DUPLICATE_WINDOW.total_seconds() == 60 * 60


def test_topup_bonus_claim_marks_matching_reward_inside_hour_as_skipped():
    cursor = _TopupClaimCursor(duplicate_award={"id": 62})

    assert _claim_topup(cursor) == "duplicate"

    duplicate_params = cursor.calls[0][1]
    insert_params = cursor.calls[1][1]
    assert duplicate_params[3] == datetime(2026, 8, 27, 9, 32, 25)
    assert duplicate_params[4] == datetime(2026, 8, 27, 11, 32, 25)
    assert insert_params[5] == 0
    assert insert_params[7] == "skipped_duplicate"
    assert insert_params[8] == "skipped"


def test_topup_bonus_claim_awards_when_hour_has_no_matching_reward():
    cursor = _TopupClaimCursor()

    assert _claim_topup(cursor) == "awarded"

    insert_params = cursor.calls[1][1]
    assert insert_params[5] == 300
    assert insert_params[7] == "awarded"
    assert insert_params[8] == "pending"


def test_topup_bonus_claim_returns_exists_for_already_processed_topup():
    cursor = _TopupClaimCursor(insert_rowcount=0)

    assert _claim_topup(cursor) == "exists"


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


def test_topup_bonus_rule_rejects_unknown_reward_type():
    with pytest.raises(ValueError, match="Неизвестный тип награды"):
        save_topup_bonus_settings(
            1,
            is_enabled=True,
            message_template="Тест",
            rules=[{"min_amount": 1000, "bonus_amount": 500, "reward_type": "diamonds"}],
        )


def test_render_topup_bonus_message_supports_token_rewards():
    message = render_topup_bonus_message(
        "Начислено {reward_amount} {reward_name}, баланс {token_balance}",
        {"reward_amount": 3, "reward_type": "tokens", "token_balance": 8},
    )

    assert message == "Начислено 3 жет., баланс 8"


def test_resolve_enabled_at_preserves_original_activation_when_settings_are_edited():
    enabled_at = datetime(2026, 8, 19, 10, 30)

    assert (
        _resolve_enabled_at(
            {"is_enabled": 1, "enabled_at": enabled_at},
            is_enabled=True,
            now=datetime(2026, 8, 21, 12, 0),
        )
        == enabled_at
    )


def test_resolve_enabled_at_sets_activation_only_when_feature_is_enabled():
    now = datetime(2026, 8, 21, 12, 0)

    assert _resolve_enabled_at(None, is_enabled=True, now=now) == now
    assert _resolve_enabled_at({"is_enabled": 1}, is_enabled=False, now=now) is None


def test_welcome_reward_requires_at_least_one_enabled_reward():
    with pytest.raises(ValueError, match="хотя бы один тип"):
        save_welcome_reward_settings(
            1,
            is_enabled=True,
            cm_bonus_amount=0,
            token_amount=0,
        )


class _WelcomeCursor:
    def __init__(self):
        self.fetchone_results = [
            {
                "welcome_reward_enabled": 1,
                "welcome_cm_bonus_amount": 150,
                "welcome_token_amount": 2,
            },
            None,
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        return None

    def fetchone(self):
        return self.fetchone_results.pop(0)


class _WelcomeConnection:
    def __init__(self):
        self.cursor_obj = _WelcomeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("welcome reward should not roll back")

    def close(self):
        self.closed = True


def test_first_authorization_can_award_kb_and_tokens_together(monkeypatch):
    connection = _WelcomeConnection()
    awarded = []

    monkeypatch.setattr("app.services.topup_bonuses.get_db_connection", lambda: connection)
    monkeypatch.setattr(
        "app.services.topup_bonuses.add_cm_bonus_transaction",
        lambda **kwargs: awarded.append(("cm_bonus", kwargs["amount"])) or True,
    )
    monkeypatch.setattr(
        "app.services.topup_bonuses.add_guest_token_transaction",
        lambda **kwargs: awarded.append(("tokens", kwargs["amount"])) or True,
    )

    result = award_first_authorization_reward(guest_id=10, club_id=2)

    assert result == {"cm_bonus_amount": 150, "token_amount": 2}
    assert awarded == [("cm_bonus", 150), ("tokens", 2)]
    assert connection.committed is True
    assert connection.closed is True
