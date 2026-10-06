"""Paused guest mutations and HTTP/callback boundaries use the real services."""

import importlib

import pytest
from flask import Flask

from app import core
from app.routes.guest import guest_bp
from app.routes.guest import main as guest_routes
from app.routes.owner import owner_bp
from app.services import cases, cm_bonuses, prize_claims, wheel
from app.services.club_service import ClubServiceDisabled
from tests.test_gizmo_reward_journey import CLUB, imported, ready, wallets  # noqa: F401

owner_routes = importlib.import_module("app.routes.owner.prize_claims")


@pytest.fixture
def operations(ready, monkeypatch):  # noqa: F811
    for module in (cases, wheel, cm_bonuses, prize_claims):
        monkeypatch.setattr(module, "get_db_connection", lambda: ready)
        for attr in (
            "ensure_case_tables",
            "ensure_token_tables",
            "ensure_cm_bonus_tables",
            "ensure_prize_claim_tables",
            "ensure_wheel_prize_bonus_columns",
        ):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, lambda cursor: None)
    monkeypatch.setattr(wheel, "get_wheel_settings", lambda cid: None)
    monkeypatch.setattr(
        wheel,
        "get_guest_missions_with_progress",
        lambda gid, cid: [dict(id=1, is_completed=True, token_reward=3, cm_bonus_reward=100, reward_text="Приз")],
    )
    ready.db.execute("INSERT INTO cm_bonus_balances VALUES (?,10,100,NULL)", (CLUB,))
    ready.db.execute("INSERT INTO guest_wheel_token_balances VALUES (?,10,20,NULL)", (CLUB,))
    ready.commit()
    return ready


@pytest.mark.parametrize("operation", ["case", "wheel", "redeem", "missions", "streak"])
def test_pause_prevents_guest_debits_awards_and_claims(operations, monkeypatch, operation):
    if operation == "streak":
        monkeypatch.setattr(wheel, "get_wheel_settings", lambda cid: dict(is_enabled=1, tokens_start_date="2026-01-01"))
    tables = (
        "cm_bonus_balances",
        "guest_wheel_token_balances",
        "cm_bonus_transactions",
        "guest_wheel_token_transactions",
        "guest_case_openings",
        "guest_prize_claims",
        "cm_bonus_redeem_requests",
        "guest_mission_completions",
    )
    before = {t: operations.records(t) for t in tables}
    calls = dict(
        case=lambda: cases.open_case(10, CLUB, 1),
        wheel=lambda: wheel.save_guest_wheel_spin(10, CLUB),
        redeem=lambda: cm_bonuses.redeem_cm_bonuses(dict(guest_id=10, club_id=CLUB)),
        missions=lambda: wheel.sync_guest_wheel_tokens(10, CLUB),
        streak=lambda: wheel.sync_guest_wheel_tokens(10, CLUB),
    )
    with pytest.raises(ClubServiceDisabled):
        calls[operation]()
    assert {t: operations.records(t) for t in tables} == before


@pytest.fixture
def claim(operations):
    operations.db.execute("ALTER TABLE guest_prize_claims ADD COLUMN issued_by_telegram_id INT")
    operations.db.execute("ALTER TABLE guest_prize_claims ADD COLUMN issued_by_user_id INT")
    operations.db.execute(
        """INSERT INTO guest_prize_claims
        (id,club_id,guest_id,prize_name,status,admin_chat_id) VALUES (1,?,10,'Тест','notified','328908187')""",
        (CLUB,),
    )
    operations.db.execute(
        """INSERT INTO cm_bonus_redeem_requests
        (id,club_id,guest_id,amount,status,admin_chat_id) VALUES (1,?,10,50,'notified','328908187')""",
        (CLUB,),
    )
    operations.commit()
    return operations


@pytest.mark.parametrize("kind", ["prize", "redeem"])
@pytest.mark.parametrize(
    "stored,incoming", [(None, 328908187), ("", 328908187), ("328908187", None), ("328908187", 999)]
)
def test_callback_cannot_confirm_without_matching_chat(claim, kind, stored, incoming):
    table = "guest_prize_claims" if kind == "prize" else "cm_bonus_redeem_requests"
    claim.db.execute(f"UPDATE {table} SET admin_chat_id=? WHERE id=1", (stored,))
    claim.commit()
    before = claim.records(table)
    handler = (
        prize_claims.mark_prize_claim_issued_by_telegram
        if kind == "prize"
        else cm_bonuses.mark_cm_bonus_redeem_credited_by_telegram
    )
    assert handler(1, incoming, 328908187)["error"] == "wrong_chat"
    assert claim.records(table) == before


@pytest.fixture
def web(claim, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(guest_bp)
    app.register_blueprint(owner_bp)
    core.register_csrf_protection(app)
    core.register_club_service_gate(app)
    # Simulate pause after the web gate passed. The service must see DB state.
    monkeypatch.setattr(core, "is_club_service_enabled", lambda cid: True)
    from app.services import guest_management

    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kw: False)
    monkeypatch.setattr(guest_routes, "get_guest_by_id", lambda gid, cid: dict(guest_id=10, club_id=CLUB))
    monkeypatch.setattr(guest_routes, "get_game_mode", lambda cid: "cases")
    monkeypatch.setattr(guest_routes, "get_wheel_settings", lambda cid: dict(is_enabled=1, spin_cost=2))
    monkeypatch.setattr(guest_routes, "get_guest_tokens", lambda *a: 20)
    monkeypatch.setattr(guest_routes, "get_wheel_prizes", lambda cid: [dict(id=1)])
    for endpoint in ("auth.login", "admin.clubs_list", "reception.dashboard"):
        app.add_url_rule("/test/" + endpoint, endpoint, lambda: "redirect target")
    return app.test_client()


def login(client, **fields):
    with client.session_transaction() as session:
        session.clear()
        session.update(_csrf_token="test-token", **fields)


@pytest.mark.parametrize("path", ["/guest/api/cases/1/open", "/guest/api/cm-bonuses/redeem", "/guest/api/wheel/spin"])
def test_pause_after_http_gate_returns_403_without_writes(web, claim, path):
    login(web, guest_logged_in=True, guest_id=10, guest_club_id=CLUB)
    response = web.post(path, headers={"X-CSRF-Token": "test-token", "Accept": "application/json"})
    assert response.status_code == 403
    assert response.json["error"] == "club_service_disabled"
    assert not claim.records("cm_bonus_transactions")
    assert not claim.records("guest_wheel_token_transactions")


@pytest.mark.parametrize("role", [None, "reception", "admin", "guest"])
def test_owner_issue_rejects_other_roles(web, claim, role):
    login(web, **(dict(user_id=1, role=role, club_id=CLUB) if role else {}))
    response = web.post("/owner/prize-claims/1/issue", headers={"X-CSRF-Token": "test-token"})
    assert response.status_code == 302
    assert claim.records("guest_prize_claims")[0]["status"] == "notified"


def test_owner_csrf_and_cross_club_scope(web, claim):
    login(web, user_id=1, role="owner", club_id=CLUB)
    assert web.post("/owner/prize-claims/1/issue", headers={"Accept": "application/json"}).status_code == 400
    login(web, user_id=1, role="owner", club_id=2)
    response = web.post("/owner/prize-claims/1/issue", data={"club_id": CLUB}, headers={"X-CSRF-Token": "test-token"})
    assert response.status_code == 302
    assert claim.records("guest_prize_claims")[0]["status"] == "notified"
    login(web, user_id=1, role="owner", club_id=CLUB)
    assert web.post("/owner/prize-claims/1/issue", headers={"X-CSRF-Token": "test-token"}).status_code == 302
    assert claim.records("guest_prize_claims")[0]["status"] == "issued"
