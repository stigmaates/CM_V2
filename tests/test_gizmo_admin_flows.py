import pytest

from app.integrations.gizmo_sync import atomic_json
from app.services import first_visit_survey as surveys
from app.services import topup_bonuses as topups
from scripts import verify_gizmo_admin_flows as check
from tests.test_gizmo_guest_features import CLUB, GuestCursor, imported, wallets  # noqa: F401


class AdminCursor(GuestCursor):
    def execute(self, sql, params=()):
        if "information_schema.TABLES" in sql:
            self.special = {"engine": "InnoDB"}
            return
        sql = sql.replace("UTC_TIMESTAMP() - INTERVAL 24 HOUR", "datetime('now','-1 day')")
        sql = sql.replace("UTC_TIMESTAMP()", "CURRENT_TIMESTAMP").replace("NOW()", "CURRENT_TIMESTAMP")
        return super().execute(sql, params)


@pytest.fixture
def ready(wallets, tmp_path, monkeypatch):  # noqa: F811
    conn = wallets
    monkeypatch.setattr(conn, "cursor", lambda: AdminCursor(conn))
    conn.db.executescript("""
      ALTER TABLE clubs ADD COLUMN name TEXT;
      ALTER TABLE clubs ADD COLUMN owner_id INT;
      ALTER TABLE clubs ADD COLUMN cm_bonus_admin_chat_id TEXT;
      INSERT INTO clubs VALUES(900002,'gizmo',0,1,'Gizmo — проверка подключения на стейдже',NULL,NULL);
      CREATE TABLE club_topup_bonus_settings(club_id INT PRIMARY KEY,message_template TEXT);
      CREATE TABLE guest_topup_bonus_awards(id INTEGER PRIMARY KEY,club_id INT,guest_id INT,topup_id INT,rule_id INT,topup_amount NUMERIC,rule_min_amount NUMERIC,bonus_amount INT,reward_type TEXT,status TEXT,delivery_status TEXT,telegram_id INT,message_text TEXT,error_text TEXT,reviewed_by INT,reviewed_at TEXT,rejection_reason TEXT,reviewed_by_telegram_id INT,reviewed_by_username TEXT);
      CREATE TABLE guest_telegram_link_requests(id INTEGER PRIMARY KEY,club_id INT,guest_id INT,telegram_id INT,telegram_phone TEXT,lg_phone TEXT,admin_chat_id TEXT,status TEXT DEFAULT 'pending',created_at TEXT,reviewed_at TEXT,reviewed_by INT);
      CREATE TABLE first_visit_surveys(id INTEGER PRIMARY KEY,club_id INT,guest_id INT,telegram_id INT,status TEXT,rating INT,bonus_amount INT,bonus_awarded INT DEFAULT 0,feedback_text TEXT,started_at TEXT,completed_at TEXT,updated_at TEXT);
    """)
    conn.commit()
    monkeypatch.setattr(check, "get_db_connection", lambda: conn)
    monkeypatch.setattr(check, "require_stage_environment", lambda: None)
    atomic_json(tmp_path / "acceptance-900001.json", {"test_club_id": 900002})
    atomic_json(tmp_path / "sync-900002.json", {"enabled": False})
    return conn, tmp_path


def test_stage_runner_real_services_and_rollback(ready):
    conn, directory = ready
    result = check.run(directory=directory)
    assert result["status"] == "complete"
    assert result["phone_contact_link"] and result["phone_admin_approval"]
    assert result["disabled_topup_award_blocked"] and result["disabled_survey_award_blocked"]
    assert result["topup_approval_not_duplicated"] and result["survey_award_not_duplicated"]
    assert result["test_rows_rolled_back"]
    assert not conn.records("guest_telegram_link_requests")
    assert not conn.records("cm_bonus_transactions")


def test_runner_failure_rolls_back_earlier_approval_and_club_flag(ready, monkeypatch):
    conn, directory = ready
    before = check.totals(conn, 900002)

    def fail(**kwargs):
        raise ValueError("injected ledger error")

    monkeypatch.setattr(surveys, "add_cm_bonus_transaction", fail)
    with pytest.raises(ValueError, match="injected"):
        check.run(directory=directory)
    assert check.totals(conn, 900002) == before


def test_survey_failure_rolls_back_wallet_write(ready, monkeypatch):
    conn, _ = ready
    conn.db.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=?", (CLUB,))
    conn.db.execute(
        "INSERT INTO first_visit_surveys(id,club_id,guest_id,telegram_id,status,bonus_amount) VALUES(1,?,10,123,'awaiting_feedback',100)",
        (CLUB,),
    )
    conn.commit()
    monkeypatch.setattr(surveys, "ensure_first_visit_survey_tables", lambda cur: None)
    actual = surveys.add_cm_bonus_transaction

    def fail_after_write(**kwargs):
        actual(**kwargs)
        raise ValueError("injected after wallet write")

    monkeypatch.setattr(surveys, "add_cm_bonus_transaction", fail_after_write)
    with pytest.raises(ValueError, match="injected"):
        surveys.complete_survey_and_award(conn, 1, "test")
    assert not conn.records("cm_bonus_transactions")
    assert not conn.records("cm_bonus_balances")
    assert conn.records("first_visit_surveys")[0]["status"] == "awaiting_feedback"


@pytest.mark.parametrize("method,args", [(surveys.mark_survey_started, (1,)), (surveys.save_survey_rating, (1, 5))])
def test_old_survey_buttons_blocked_when_service_off(ready, monkeypatch, method, args):
    from app.services.club_service import ClubServiceDisabled

    conn, _ = ready
    conn.db.execute(
        "INSERT INTO first_visit_surveys(id,club_id,guest_id,telegram_id,status,bonus_amount) VALUES(1,?,10,123,'invited',100)",
        (CLUB,),
    )
    conn.commit()
    monkeypatch.setattr(surveys, "ensure_first_visit_survey_tables", lambda cur: None)
    with pytest.raises(ClubServiceDisabled):
        method(conn, *args)
    assert conn.records("first_visit_surveys")[0]["status"] == "invited"


def test_disabled_survey_is_not_created_or_sent(ready, monkeypatch):
    from app.services import outbound_policy

    conn, _ = ready
    monkeypatch.setattr(surveys, "ensure_first_visit_survey_tables", lambda cur: None)
    assert surveys.create_first_visit_survey(conn, {}, {"club_id": CLUB}) is None
    conn.db.execute(
        "INSERT INTO first_visit_surveys(id,club_id,guest_id,telegram_id,status,bonus_amount) VALUES(1,?,10,123,'created',100)",
        (CLUB,),
    )
    conn.commit()
    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: False)
    monkeypatch.setattr(surveys, "_tg_request", lambda *args: pytest.fail("disabled invitation sent"))
    assert not surveys.send_first_visit_survey_invite(conn, 1, "test")
    assert conn.records("first_visit_surveys")[0]["status"] == "created"


def test_topup_admin_notification_is_not_sent_for_disabled_club(monkeypatch):
    from app.services import outbound_policy

    monkeypatch.setattr(outbound_policy, "outbound_blocked", lambda: False)
    monkeypatch.setattr(
        topups, "get_topup_bonus_approval_by_id", lambda aid: {"service_enabled": 0, "status": "pending_approval"}
    )
    assert topups.notify_topup_bonus_admin_chat(1)["status"] == "service_disabled"
