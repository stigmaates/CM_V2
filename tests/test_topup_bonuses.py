import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.services.topup_bonuses import (
    TOPUP_BONUS_DUPLICATE_WINDOW,
    _claim_topup_bonus_award,
    _resolve_enabled_at,
    award_first_authorization_reward,
    render_topup_bonus_message,
    review_topup_bonus_award,
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
        rule={"id": 7, "min_amount": Decimal("1000.00"), "bonus_amount": 300, "reward_type": "cm_bonus"},
        awarded_at=datetime(2026, 8, 27, 10, 33, 6),
    )


def test_topup_bonus_duplicate_window_is_one_hour():
    assert TOPUP_BONUS_DUPLICATE_WINDOW.total_seconds() == 60 * 60


def test_topup_bonus_claim_marks_matching_reward_inside_hour_as_skipped():
    cursor = _TopupClaimCursor(duplicate_award={"id": 62})

    assert _claim_topup(cursor) == "duplicate"

    duplicate_params = cursor.calls[0][1]
    insert_params = cursor.calls[1][1]
    assert duplicate_params == (2, 15173, datetime(2026, 8, 27, 9, 32, 25), datetime(2026, 8, 27, 11, 32, 25))
    assert insert_params[6] == 0
    assert insert_params[8] == "skipped_duplicate"
    assert insert_params[9] == "skipped"


def test_topup_bonus_claim_waits_for_approval_when_hour_has_no_matching_reward():
    cursor = _TopupClaimCursor()

    assert _claim_topup(cursor) == "pending"

    insert_params = cursor.calls[1][1]
    assert insert_params[5] == Decimal("1000.00")
    assert insert_params[6] == 300
    assert insert_params[8] == "pending_approval"
    assert insert_params[9] == "waiting_approval"


def test_topup_bonus_claim_returns_exists_for_already_processed_topup():
    cursor = _TopupClaimCursor(insert_rowcount=0)

    assert _claim_topup(cursor) == "exists"


class _ReviewCursor:
    def __init__(self, fetchone_results):
        self.fetchone_results = list(fetchone_results)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return self.fetchone_results.pop(0)


class _ReviewConnection:
    def __init__(self, fetchone_results):
        self.cursor_obj = _ReviewCursor(fetchone_results)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _pending_award(**overrides):
    value = {
        "id": 41,
        "club_id": 2,
        "topup_id": 699621,
        "guest_id": 15173,
        "topup_amount": Decimal("1500.00"),
        "rule_min_amount": Decimal("1000.00"),
        "bonus_amount": 300,
        "reward_type": "cm_bonus",
        "status": "pending_approval",
        "telegram_id": 123,
        "fio": "Морозов Дмитрий Антонович",
        "club_name": "WALLZ",
        "message_template": "{first_name}, начислено {reward_amount} {reward_name}",
    }
    value.update(overrides)
    return value


def test_topup_bonus_is_granted_only_after_approval(monkeypatch):
    connection = _ReviewConnection([_pending_award(), {"cm_balance": 700, "token_balance": 2}])
    transactions = []
    monkeypatch.setattr("app.services.topup_bonuses.get_db_connection", lambda: connection)
    monkeypatch.setattr(
        "app.services.topup_bonuses.add_cm_bonus_transaction",
        lambda **kwargs: transactions.append(kwargs) or True,
    )

    result = review_topup_bonus_award(award_id=41, club_id=2, user_id=9, approve=True)

    assert result == {"ok": True, "status": "awarded", "delivery_status": "pending"}
    assert transactions[0]["amount"] == 300
    assert transactions[0]["source_id"] == "699621"
    update_query, update_params = connection.cursor_obj.calls[-1]
    assert "status = 'awarded'" in update_query
    assert update_params[0] == "pending"
    assert "Дмитрий, начислено 300 КБ" in update_params[1]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_rejected_topup_bonus_does_not_change_balance(monkeypatch):
    connection = _ReviewConnection([_pending_award()])
    monkeypatch.setattr("app.services.topup_bonuses.get_db_connection", lambda: connection)
    monkeypatch.setattr(
        "app.services.topup_bonuses.add_cm_bonus_transaction",
        lambda **kwargs: pytest.fail("rejected reward must not change balance"),
    )

    result = review_topup_bonus_award(
        award_id=41,
        club_id=2,
        user_id=9,
        approve=False,
        rejection_reason="Пополнение отменено",
    )

    assert result == {"ok": True, "status": "rejected"}
    update_query, update_params = connection.cursor_obj.calls[-1]
    assert "status = 'rejected'" in update_query
    assert update_params[2] == "Пополнение отменено"
    assert connection.commits == 1


def test_topup_bonus_review_cannot_be_repeated(monkeypatch):
    connection = _ReviewConnection([_pending_award(status="awarded")])
    monkeypatch.setattr("app.services.topup_bonuses.get_db_connection", lambda: connection)

    result = review_topup_bonus_award(award_id=41, club_id=2, user_id=9, approve=True)

    assert result == {"ok": False, "error": "Заявка уже обработана"}
    assert connection.commits == 0


@pytest.mark.parametrize(
    "amount,seconds,club_id,guest_id,expected",
    [
        (1000, 0, 2, 23210, "duplicate"),
        (1000, 4, 2, 23210, "duplicate"),
        (2000, 4, 2, 23210, "duplicate"),
        (3000, 4, 2, 23210, "duplicate"),
        (1000, -4, 2, 23210, "duplicate"),
        (1000, 3600, 2, 23210, "duplicate"),
        (1000, 3601, 2, 23210, "pending"),
        (1000, 4, 3, 23210, "pending"),
        (1000, 4, 2, 23211, "pending"),
    ],
)
def test_topup_cooldown_executes_sql_independently_of_amount(amount, seconds, club_id, guest_id, expected):
    # Execute the production query against real tables; only adapt driver syntax.
    # This covers sequential processing, not MySQL locking/concurrent workers.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    class Cursor:
        def __init__(self):
            self.raw = conn.cursor()

        def execute(self, query, params):
            values = [
                value.isoformat(" ")
                if isinstance(value, datetime)
                else str(value)
                if isinstance(value, Decimal)
                else value
                for value in params
            ]
            self.raw.execute(query.replace("%s", "?").replace("INSERT IGNORE", "INSERT OR IGNORE"), values)

        def fetchone(self):
            return self.raw.fetchone()

        @property
        def rowcount(self):
            return self.raw.rowcount

    try:
        conn.executescript("""
            CREATE TABLE guest_balance_topups (
                club_id INTEGER, topup_id INTEGER, guest_id INTEGER,
                amount NUMERIC, topup_at TEXT
            );
            CREATE TABLE guest_topup_bonus_awards (
                id INTEGER PRIMARY KEY, club_id INTEGER, topup_id INTEGER, guest_id INTEGER,
                rule_id INTEGER, topup_amount NUMERIC, rule_min_amount NUMERIC, bonus_amount INTEGER,
                reward_type TEXT, status TEXT, delivery_status TEXT, telegram_id INTEGER,
                created_at TEXT, UNIQUE(club_id, topup_id)
            );
        """)
        cursor = Cursor()
        first_at = datetime(2026, 9, 6, 15, 34, 32)
        for topup_id, club, guest, value, when, outcome in [
            (701980, 2, 23210, 2000, first_at, "pending"),
            (701981, club_id, guest_id, amount, first_at + timedelta(seconds=seconds), expected),
        ]:
            cursor.execute(
                "INSERT INTO guest_balance_topups VALUES (%s, %s, %s, %s, %s)",
                (club, topup_id, guest, value, when),
            )
            assert (
                _claim_topup_bonus_award(
                    cursor,
                    club_id=club,
                    topup={"topup_id": topup_id, "guest_id": guest, "amount": Decimal(value), "topup_at": when},
                    rule={
                        "id": 7,
                        "min_amount": Decimal("1000.00"),
                        "bonus_amount": 300,
                        "reward_type": "cm_bonus",
                    },
                    awarded_at=datetime(2026, 9, 6, 15, 36, 6),
                )
                == outcome
            )
        row = conn.execute("SELECT * FROM guest_topup_bonus_awards WHERE topup_id = 701981").fetchone()
        assert row["bonus_amount"] == (0 if expected == "duplicate" else 300)
        assert row["status"] == ("skipped_duplicate" if expected == "duplicate" else "pending_approval")
    finally:
        conn.close()


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
