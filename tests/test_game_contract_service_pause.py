"""Disabled clubs cannot acquire or recover contract rewards, including mid-sync."""

import pytest

from app.services import game_contracts as contracts
from app.services.club_service import ClubServiceDisabled
from tests.test_gizmo_guest_features import CLUB, GuestCursor, imported, wallets  # noqa: F401


class ContractCursor(GuestCursor):
    def execute(self, sql, params=()):
        self.owner.statements.append(sql)
        sql = sql.replace("DATE_SUB(%s, INTERVAL 30 DAY)", "datetime(%s, '-30 day')")
        return super().execute(sql, params)


@pytest.fixture
def ready(wallets, monkeypatch):  # noqa: F811
    wallets.statements = []
    monkeypatch.setattr(wallets, "cursor", lambda: ContractCursor(wallets))
    monkeypatch.setattr(contracts, "get_db_connection", lambda: wallets)
    monkeypatch.setattr(contracts, "ensure_token_tables", lambda cur: None)
    monkeypatch.setattr(contracts, "ensure_cm_bonus_tables", lambda cur: None)
    wallets.db.executescript("""
      CREATE TABLE guest_game_contracts(id INTEGER PRIMARY KEY,club_id INT,guest_id INT,game TEXT,title TEXT,
          status TEXT,reward_tokens INT,reward_bonus INT,reward_claimed_at TEXT,completed_at TEXT,updated_at TEXT);
      CREATE TABLE guest_steam_accounts(club_id INT,guest_id INT,steam_id TEXT);
    """)
    wallets.db.execute("INSERT INTO guest_steam_accounts VALUES (?,10,'76561190000000000')", (CLUB,))
    for cid in (CLUB, 2):
        wallets.db.execute(
            """INSERT INTO guest_game_contracts(club_id,guest_id,game,title,status,reward_tokens,reward_bonus)
            VALUES (?,10,'dota2','Тест','completed',3,100)""",
            (cid,),
        )
    wallets.commit()
    return wallets


@pytest.mark.parametrize(
    "operation",
    [
        lambda: contracts.repair_missing_contract_rewards(CLUB, 10),
        lambda: contracts.evaluate_contracts_for_guest(CLUB, 10, "dota2"),
        lambda: contracts.generate_weekly_contracts(CLUB, 10, "dota2"),
        lambda: contracts.accept_weekly_contracts(CLUB, 10, "dota2", [1, 2, 3]),
        lambda: contracts.reroll_guest_contracts(CLUB, 10, "dota2"),
    ],
)
def test_paused_club_rejects_contract_mutations_before_any_write(ready, operation):
    before = ready.records("guest_game_contracts")
    with pytest.raises(ClubServiceDisabled):
        operation()
    assert ready.records("guest_game_contracts") == before
    assert not ready.records("cm_bonus_transactions")
    assert not ready.records("guest_wheel_token_transactions")
    assert "FOR UPDATE" in ready.statements[-1]


@pytest.mark.parametrize("cid", [CLUB, 2])
def test_resume_repairs_rewards_once_and_only_for_selected_club(ready, cid):
    ready.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (cid,))
    ready.commit()
    assert contracts.repair_missing_contract_rewards(cid, 10) == 1
    assert contracts.repair_missing_contract_rewards(cid, 10) == 0
    for table, amount in (("guest_wheel_token_transactions", 3), ("cm_bonus_transactions", 100)):
        rows = ready.records(table)
        assert len(rows) == 1 and rows[0]["club_id"] == cid and rows[0]["amount"] == amount


def test_failed_bonus_credit_rolls_back_token_credit_too(ready, monkeypatch):
    ready.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (CLUB,))
    ready.commit()

    def fail(*args, **kwargs):
        raise ValueError("injected bonus failure")

    monkeypatch.setattr(contracts, "add_cm_bonus_transaction", fail)
    with pytest.raises(ValueError, match="injected"):
        contracts.repair_missing_contract_rewards(CLUB, 10)
    assert not ready.records("guest_wheel_token_transactions")
    assert not ready.records("guest_wheel_token_balances")
    assert all(not row["reward_claimed_at"] for row in ready.records("guest_game_contracts"))


def test_pause_during_match_fetch_prevents_save_and_reward(ready, monkeypatch):
    ready.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (CLUB,))
    ready.commit()

    def fetch(*args, **kwargs):
        ready.db.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=?", (CLUB,))
        ready.commit()
        return {"matches": [{"id": 1}]}

    monkeypatch.setattr(contracts, "fetch_dota_recent_matches", fetch)
    monkeypatch.setattr(contracts, "_upsert_match", lambda *a, **kw: pytest.fail("Paused club imported match"))
    monkeypatch.setattr(contracts, "_record_sync_state", lambda *a, **kw: pytest.fail("Pause was logged as sync error"))
    with pytest.raises(ClubServiceDisabled):
        contracts.sync_contracts_for_guest(CLUB, 10, "dota2")
    assert not ready.records("guest_wheel_token_transactions")


def test_paused_club_does_not_call_external_game_api(ready, monkeypatch):
    monkeypatch.setattr(
        contracts, "fetch_dota_recent_matches", lambda *a, **kw: pytest.fail("Paused club called game API")
    )
    with pytest.raises(ClubServiceDisabled):
        contracts.sync_contracts_for_guest(CLUB, 10, "dota2")


@pytest.mark.parametrize(
    "path",
    [
        "/guest/contracts/dota2/generate",
        "/guest/contracts/dota2/accept",
        "/guest/contracts/dota2/refresh",
        "/guest/api/game-contracts/sync",
    ],
)
def test_contract_web_requests_return_pause_instead_of_500(ready, monkeypatch, path):
    from flask import Flask

    from app import core
    from app.routes.guest import guest_bp
    from app.routes.guest import main as routes
    from app.services import guest_management

    app = Flask(__name__)
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(guest_bp)
    core.register_club_service_gate(app)
    monkeypatch.setattr(core, "is_club_service_enabled", lambda cid: True)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kw: False)
    monkeypatch.setattr(routes, "is_game_contracts_enabled", lambda cid: True)
    monkeypatch.setattr(routes, "is_rate_limited", lambda *a, **kw: False)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session.update(guest_logged_in=True, guest_id=10, guest_club_id=CLUB)
        response = client.post(path, json={"contract_ids": [1, 2, 3]})
        assert response.status_code == 403
        assert response.json["error"] == "club_service_disabled"


def test_stage_probe_uses_database_guards_without_writes(ready, tmp_path, monkeypatch):
    from app.integrations.gizmo_sync import atomic_json
    from scripts import verify_gizmo_contract_pause as probe

    monkeypatch.setattr(probe, "CLUB", CLUB)
    monkeypatch.setattr(probe, "GUEST", 10)
    monkeypatch.setattr(probe, "require_stage_environment", lambda: None)
    monkeypatch.setattr(probe, "verify_target", lambda conn, directory: None)
    monkeypatch.setattr(probe, "get_db_connection", lambda: ready)
    atomic_json(tmp_path / f"sync-{CLUB}.json", dict(enabled=False))
    result = probe.run(directory=tmp_path)
    assert result["status"] == "complete"
    assert len(result["checks"]) == 6
    assert not ready.records("cm_bonus_transactions")
    with probe.SelectConnection(ready).cursor() as cursor:
        with pytest.raises(RuntimeError, match="forbidden"):
            cursor.execute("UPDATE clubs SET service_enabled=1")
