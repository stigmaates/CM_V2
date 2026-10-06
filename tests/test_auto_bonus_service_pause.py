"""A stale audience must not receive rewards after service has been disabled."""

import pytest

from app.services import mailing, outbound_policy
from scripts import process_auto_mailings as worker
from tests.test_gizmo_guest_features import CLUB, GuestCursor, imported, wallets  # noqa: F401


class MailingCursor(GuestCursor):
    def execute(self, sql, params=()):
        self.owner.statements.append(sql)
        return super().execute(sql.replace("NOW()", "CURRENT_TIMESTAMP"), params)

    def executemany(self, sql, values):
        for params in values:
            self.execute(sql, params)


@pytest.fixture
def ready(wallets, monkeypatch):  # noqa: F811
    wallets.statements = []
    wallets.db.executescript("""
      UPDATE clubs SET service_enabled=1;
      CREATE TABLE auto_mailing_settings(id INTEGER PRIMARY KEY,last_run_at TEXT,updated_at TEXT,last_mailing_id INT);
      INSERT INTO auto_mailing_settings(id) VALUES(1);
      CREATE TABLE mailings(id INTEGER PRIMARY KEY,club_id INT,segment_id INT,filters_json TEXT,message_text TEXT,parse_mode TEXT,status TEXT,recipients_count INT);
      CREATE TABLE mailing_recipients(id INTEGER PRIMARY KEY,mailing_id INT,guest_id INT,telegram_id INT,message_text TEXT,status TEXT,error_text TEXT,sent_at TEXT);
      CREATE TABLE auto_mailing_logs(id INTEGER PRIMARY KEY,club_id INT,automation_code TEXT,guest_id INT,telegram_id INT,mailing_id INT,mailing_recipient_id INT,status TEXT,error_text TEXT,sent_at TEXT);
    """)
    monkeypatch.setattr(wallets, "cursor", lambda: MailingCursor(wallets))
    monkeypatch.setattr(worker, "ensure_cm_bonus_tables", lambda cur: None)
    monkeypatch.setattr(worker, "_ensure_mailing_recipient_message_column", lambda cur: None)
    monkeypatch.setattr(mailing, "_ensure_mailing_recipient_message_column", lambda cur: None)
    monkeypatch.setattr(outbound_policy, "ensure_outbound_allowed", lambda: None)
    monkeypatch.setattr(
        worker,
        "get_inactive_auto_mailing_recipients",
        lambda **kwargs: [dict(guest_id=10, telegram_id=123), dict(guest_id=11, telegram_id=124)],
    )
    monkeypatch.setattr(worker, "process_one_mailing", lambda *args: None)  # No network in database tests.
    return wallets


SETTING = dict(id=1, club_id=CLUB, code="inactive_14_bonus", bonus_amount=200, message_text="Тест")


def test_stale_setting_cannot_award_or_queue_after_disable(ready):
    ready.db.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=?", (CLUB,))
    ready.commit()
    assert worker.process_inactive_14_bonus(ready, SETTING) == 0
    assert ready.records("mailings") == ready.records("cm_bonus_transactions") == []
    assert any("FOR UPDATE" in sql for sql in ready.statements)


def test_award_failure_rolls_back_queue_and_every_wallet(ready, monkeypatch):
    actual = worker.add_cm_bonus_transaction

    def award(**kwargs):
        if kwargs["guest_id"] == 11:
            raise ValueError("injected second award failure")
        return actual(**kwargs)

    monkeypatch.setattr(worker, "add_cm_bonus_transaction", award)
    with pytest.raises(ValueError, match="injected"):
        worker.process_inactive_14_bonus(ready, SETTING)
    for table in ("mailings", "mailing_recipients", "cm_bonus_transactions", "cm_bonus_balances"):
        assert ready.records(table) == []


@pytest.mark.parametrize("enabled", [1, None])
def test_queue_and_rewards_commit_together_before_delivery(ready, monkeypatch, enabled):
    ready.db.execute("UPDATE clubs SET service_enabled=? WHERE club_id=?", (enabled, CLUB))
    ready.commit()

    def send(conn, mailing_id):
        assert not conn.db.in_transaction
        assert len(conn.records("cm_bonus_transactions")) == 2
        assert len(conn.records("mailing_recipients")) == 2

    monkeypatch.setattr(worker, "process_one_mailing", send)
    assert worker.process_inactive_14_bonus(ready, SETTING) == 2
    assert [r["balance"] for r in ready.records("cm_bonus_balances")] == [200, 200]
