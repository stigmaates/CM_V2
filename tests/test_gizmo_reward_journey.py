"""Service journey on imported rows, with transaction rollback and no delivery."""

from datetime import datetime

import pytest

from app.services import outbound_policy
from scripts import verify_gizmo_reward_journey as journey
from tests.test_gizmo_guest_features import CLUB, GuestCursor, imported, wallets  # noqa: F401


class JourneyCursor(GuestCursor):
    def execute(self, sql, params=()):
        if "ENGINE AS engine" in sql:
            self.special = {"engine": getattr(self.owner, "engine", "InnoDB")}
            return
        super().execute(sql, params)

    def fetchone(self):
        row = super().fetchone()
        if row:
            for field in ("date_start", "date_stop", "issued_at", "processed_at"):
                if isinstance(row.get(field), str):
                    row[field] = datetime.fromisoformat(row[field])
        return row


@pytest.fixture
def ready(wallets, monkeypatch):  # noqa: F811
    wallets.db.executescript("""
        ALTER TABLE clubs ADD COLUMN timezone TEXT DEFAULT 'Asia/Yekaterinburg';
        CREATE TABLE club_wheel_settings (club_id INT PRIMARY KEY,tokens_start_date TEXT,is_enabled INT);
        CREATE TABLE mission_templates (id INTEGER PRIMARY KEY,code TEXT,name TEXT,short_description TEXT,target_metric TEXT,config_schema TEXT);
        INSERT INTO mission_templates VALUES (1,'visit','Визит','','visits_count',NULL);
        CREATE TABLE club_missions (id INTEGER PRIMARY KEY,club_id INT,mission_template_id INT,custom_name TEXT,custom_description TEXT,
            is_enabled INT,target_amount INT,reward_text TEXT,token_reward INT,cm_bonus_reward INT,start_at TEXT,end_at TEXT,config TEXT,sort_order INT);
        CREATE TABLE guest_mission_completions (club_id INT,guest_id INT,mission_id TEXT,completed_at TEXT,UNIQUE(club_id,guest_id,mission_id));
        CREATE TABLE club_cases (id INTEGER PRIMARY KEY,club_id INT,name TEXT,description TEXT,image_url TEXT,badge_label TEXT,badge_color TEXT,
            price_tokens INT,is_active INT,sort_order INT DEFAULT 0);
        CREATE TABLE club_case_items (id INTEGER PRIMARY KEY,club_id INT,case_id INT,name TEXT,description TEXT,image_url TEXT,
            bonus_amount INT DEFAULT 0,token_amount INT DEFAULT 0,contract_refresh_amount INT DEFAULT 0,probability INT,
            rarity_label TEXT,is_active INT,sort_order INT DEFAULT 0);
        CREATE TABLE guest_case_openings (id INTEGER PRIMARY KEY,club_id INT,guest_id INT,case_id INT,item_id INT,spent_tokens INT,created_at TEXT);
        ALTER TABLE guest_prize_claims ADD COLUMN admin_chat_id TEXT;
        ALTER TABLE guest_prize_claims ADD COLUMN telegram_message_id INT;
        ALTER TABLE guest_prize_claims ADD COLUMN notify_error TEXT;
        ALTER TABLE guest_prize_claims ADD COLUMN notified_at TEXT;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN next_notify_attempt_at TEXT;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN last_notify_attempt_at TEXT;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN notify_attempts INT DEFAULT 0;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN admin_chat_id TEXT;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN telegram_message_id INT;
        ALTER TABLE cm_bonus_redeem_requests ADD COLUMN processed_by_telegram_id INT;
    """)
    monkeypatch.setattr(wallets, "cursor", lambda: JourneyCursor(wallets))
    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: True)
    yield wallets


def test_complete_journey_uses_real_services_and_rolls_back_every_write(ready):
    before = {table: ready.records(table) for table in journey.WRITE_TABLES}
    try:
        with journey.service_transaction(ready) as transaction:
            report = journey.exercise(transaction, CLUB)
        assert report["mission_reward_not_duplicated"]
        assert report["case_token_debit"] and report["case_bonus_credit"]
        assert report["physical_prize_visible_and_issued"]
        assert report["cross_club_issue_rejected"]
        assert report["manual_credit_request_idempotent"]
        assert len(ready.records("guest_case_openings")) == 2
    finally:
        ready.rollback()
    assert {table: ready.records(table) for table in journey.WRITE_TABLES} == before


def test_mid_journey_failure_cannot_commit_fixtures(ready, monkeypatch):
    before = {table: ready.records(table) for table in journey.WRITE_TABLES}
    from app.services import cases

    def fail(*args, **kwargs):
        raise ValueError("injected opening failure")

    monkeypatch.setattr(cases, "open_case", fail)
    try:
        with pytest.raises(ValueError, match="injected"):
            with journey.service_transaction(ready) as transaction:
                journey.exercise(transaction, CLUB)
    finally:
        ready.rollback()
    assert {table: ready.records(table) for table in journey.WRITE_TABLES} == before


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE test (id INT)",
        "ALTER TABLE guests ADD column x INT",
        "COMMIT",
        "DELETE FROM guests",
        "UPDATE clubs SET service_enabled=1",
        "SELECT 1; COMMIT",
    ],
)
def test_guard_rejects_implicit_commits_and_unrelated_writes(ready, sql):
    with journey.TransactionConnection(ready).cursor() as cursor:
        with pytest.raises(RuntimeError):
            cursor.execute(sql)


def test_requires_outbound_stop_even_inside_stage(ready, monkeypatch):
    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: False)
    with pytest.raises(RuntimeError, match="outbound stop"):
        with journey.service_transaction(ready):
            pytest.fail("must reject before entering")


@pytest.fixture
def server(ready, tmp_path, monkeypatch):
    import json

    ready.db.execute("ALTER TABLE clubs ADD COLUMN owner_id INT")
    ready.db.execute("ALTER TABLE clubs ADD COLUMN name TEXT")
    ready.db.execute("UPDATE clubs SET name=? WHERE club_id=?", (journey.TEST_NAME, CLUB))
    ready.commit()
    (tmp_path / "acceptance-7.json").write_text(json.dumps(dict(test_club_id=CLUB)))
    (tmp_path / f"sync-{CLUB}.json").write_text(json.dumps(dict(enabled=False)))
    for path in tmp_path.glob("*.json"):
        path.chmod(0o600)
    monkeypatch.setattr(journey, "require_stage_environment", lambda: None)
    monkeypatch.setattr(journey, "get_db_connection", lambda: ready)
    return ready, tmp_path


def test_server_runner_validates_club_and_verifies_full_rollback(server):
    ready, directory = server
    before = {table: ready.records(table) for table in journey.WRITE_TABLES}
    report = journey.run(7, directory=directory)
    assert report["status"] == "complete"
    assert report["test_rows_rolled_back"]
    assert {table: ready.records(table) for table in journey.WRITE_TABLES} == before


def test_server_runner_rejects_nontransactional_table_before_fixtures(server):
    ready, directory = server
    ready.engine = "MyISAM"
    with pytest.raises(RuntimeError, match="InnoDB"):
        journey.run(7, directory=directory)
    assert ready.records("guest_case_openings") == []


def test_server_runner_refuses_enabled_club(server):
    ready, directory = server
    ready.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (CLUB,))
    ready.commit()
    with pytest.raises(RuntimeError, match="service is enabled"):
        journey.run(7, directory=directory)
    assert ready.records("guest_case_openings") == []
