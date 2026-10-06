"""A token obtained before service pause cannot bind, log in or award later."""

from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask

from app.routes.guest import guest_bp
from app.routes.guest import main as routes
from app.services import guest_auth, telegram_links, topup_bonuses
from app.services.club_service import ClubServiceDisabled
from bot import main as bot
from tests.test_gizmo_guest_features import CLUB, GuestCursor, imported, wallets  # noqa: F401


class AuthCursor(GuestCursor):
    def execute(self, sql, params=()):
        self.owner.statements.append(sql)
        return super().execute(sql.replace("UTC_TIMESTAMP()", "CURRENT_TIMESTAMP"), params)


@pytest.fixture
def ready(wallets, monkeypatch):  # noqa: F811
    wallets.statements = []
    wallets.db.executescript("""
        UPDATE clubs SET service_enabled=1;
        CREATE TABLE guest_login_tokens(token TEXT PRIMARY KEY,guest_id INT,club_id INT,
          telegram_id INT,is_confirmed INT,created_at TEXT,expires_at TEXT);
        CREATE TABLE club_topup_bonus_settings(club_id INT,welcome_reward_enabled INT,
          welcome_cm_bonus_amount INT,welcome_token_amount INT);
    """)
    monkeypatch.setattr(wallets, "cursor", lambda: AuthCursor(wallets))
    for module in (guest_auth, bot, telegram_links, topup_bonuses):
        monkeypatch.setattr(module, "get_db_connection", lambda: wallets)
    monkeypatch.setattr(guest_auth, "_guest_login_tokens_club_column_ready", True)
    monkeypatch.setattr(bot, "ensure_guest_login_tokens_club_column", lambda cur: None)
    monkeypatch.setattr(topup_bonuses, "ensure_cm_bonus_tables", lambda cur: None)
    monkeypatch.setattr(topup_bonuses, "ensure_token_tables", lambda cur: None)
    return wallets


def pause(conn):
    conn.db.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=?", (CLUB,))
    conn.commit()


def test_old_token_and_new_token_blocked_after_pause(ready):
    token = guest_auth.create_guest_login_token(CLUB)
    pause(ready)
    with pytest.raises(ClubServiceDisabled):
        bot.confirm_login_token(token, 10, CLUB, 123)
    with pytest.raises(ClubServiceDisabled):
        guest_auth.create_guest_login_token(CLUB)
    rows = ready.records("guest_login_tokens")
    assert len(rows) == 1 and rows[0]["is_confirmed"] == 0
    assert any("FOR UPDATE" in sql for sql in ready.statements)


def test_contact_cannot_bind_after_pause(ready):
    pause(ready)
    with pytest.raises(ClubServiceDisabled):
        telegram_links.bind_verified_contact(10, CLUB, 123)
    guest = ready.db.execute("SELECT telegram_id FROM guests WHERE club_id=? AND guest_id=10", (CLUB,)).fetchone()
    assert guest[0] is None


def test_welcome_after_confirmation_cannot_award_after_pause(ready):
    token = guest_auth.create_guest_login_token(CLUB)
    bot.confirm_login_token(token, 10, CLUB, 123)
    pause(ready)
    with pytest.raises(ClubServiceDisabled):
        topup_bonuses.award_first_authorization_reward(10, CLUB)
    assert not ready.records("guest_wheel_token_transactions")
    assert not ready.records("cm_bonus_transactions")


@pytest.mark.parametrize("service", [1, None])
def test_enabled_and_legacy_clubs_confirm_and_award_once(ready, service):
    ready.db.execute("UPDATE clubs SET service_enabled=? WHERE club_id=?", (service, CLUB))
    ready.commit()
    token = guest_auth.create_guest_login_token(CLUB)
    bot.confirm_login_token(token, 10, CLUB, 123)
    assert topup_bonuses.award_first_authorization_reward(10, CLUB) == {"cm_bonus_amount": 0, "token_amount": 1}
    assert topup_bonuses.award_first_authorization_reward(10, CLUB) is None
    assert len(ready.records("guest_wheel_token_transactions")) == 1


def test_welcome_failure_rolls_back_both_ledgers(ready, monkeypatch):
    ready.db.execute("INSERT INTO club_topup_bonus_settings VALUES (?,1,100,2)", (CLUB,))
    ready.commit()

    def fail(**kwargs):
        raise ValueError("injected token failure")

    monkeypatch.setattr(topup_bonuses, "add_guest_token_transaction", fail)
    with pytest.raises(ValueError, match="injected"):
        topup_bonuses.award_first_authorization_reward(10, CLUB)
    assert not ready.records("cm_bonus_transactions")
    assert not ready.records("cm_bonus_balances")


@pytest.mark.parametrize("confirmed", [0, 1])
def test_browser_rejects_pre_pause_token_without_session(monkeypatch, confirmed):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(guest_bp)
    monkeypatch.setattr(routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(routes, "get_guest_login_club", lambda cid: {"club_id": CLUB, "service_enabled": 0})
    monkeypatch.setattr(
        routes,
        "get_guest_login_token",
        lambda token: dict(
            club_id=CLUB,
            guest_id=10,
            is_confirmed=confirmed,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
        ),
    )
    with app.test_client() as client:
        response = client.get("/guest/check-login?token=before-pause")
        assert response.status_code == 403
        assert response.json["error"] == "service_disabled"
        with client.session_transaction() as session:
            assert not session.get("guest_logged_in")


def test_disabled_login_page_never_creates_token(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(guest_bp)
    monkeypatch.setattr(routes, "get_guest_login_club", lambda cid: {"club_id": CLUB, "service_enabled": 0})
    monkeypatch.setattr(routes, "render_template", lambda *args, **kwargs: "paused")

    def forbidden(*args):
        pytest.fail("disabled club created a login token")

    monkeypatch.setattr(routes, "create_guest_login_token", forbidden)
    assert app.test_client().get(f"/guest/login?club_id={CLUB}").status_code == 403
