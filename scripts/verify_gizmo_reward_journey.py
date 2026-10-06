"""Exercise stage reward services in one transaction, always rolled back.

Uses only the disabled, ownerless lifecycle acceptance club. Service commits
are suppressed, all connections share the transaction, DDL is forbidden, and
HTTP sends fail the check. This checks service logic, not HTTP authorization,
concurrency between transactions, real Telegram delivery or Gizmo writes.
Auto-increment counters may advance even though all test rows are rolled back.
"""

import argparse
import json
import re
import sys
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_sync import DIRECTORY, private_json, run_lock
from app.integrations.stage import require_stage_environment
from app.services import cases, cm_bonuses, missions, outbound_policy, prize_claims, reception, wheel
from scripts.verify_gizmo_stage_lifecycle import TEST_NAME

WRITE_TABLES = {
    "guests",
    "guest_sessions",
    "club_missions",
    "guest_mission_completions",
    "club_cases",
    "club_case_items",
    "guest_case_openings",
    "guest_wheel_token_balances",
    "guest_wheel_token_transactions",
    "cm_bonus_balances",
    "cm_bonus_transactions",
    "cm_bonus_redeem_requests",
    "guest_prize_claims",
}
PHONE = "70000000000"


class GuardedCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, sql, params=()):
        clean = sql.strip()
        if ";" in clean.rstrip(";"):
            raise RuntimeError("Multiple SQL statements are forbidden during acceptance")
        if not re.match(r"^SELECT\b", clean, re.I):
            match = re.match(r"^(?:INSERT(?: IGNORE)? INTO|UPDATE)\s+(\w+)\b", clean, re.I)
            if not match or match[1].lower() not in WRITE_TABLES:
                raise RuntimeError("DDL, transaction control and unrelated writes are forbidden during acceptance")
        return self.cursor.execute(sql, params)


class TransactionConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return GuardedCursor(self.conn.cursor())

    def commit(self):
        pass  # Owner of the acceptance transaction ALWAYS rolls back.

    def close(self):
        pass

    def rollback(self):
        raise RuntimeError("Service requested rollback; abort reward acceptance")


@contextmanager
def service_transaction(conn):
    proxy = TransactionConnection(conn)
    with ExitStack() as stack:
        for module in (cases, cm_bonuses, missions, prize_claims, reception, wheel):
            stack.enter_context(patch.object(module, "get_db_connection", lambda: proxy))
        # Schema is checked before entry. Lazy DDL would implicitly commit MySQL.
        for module, flag in (
            (cases, "_case_tables_ready"),
            (cm_bonuses, "_cm_bonus_tables_ready"),
            (prize_claims, "_prize_claim_tables_ready"),
            (wheel, "_token_tables_ready"),
            (wheel, "_wheel_settings_display_columns_ready"),
            (missions, "_mission_reward_columns_ready"),
        ):
            stack.enter_context(patch.object(module, flag, True))
        # Existing mission templates are used; never seed global defaults here.
        stack.enter_context(patch.object(missions, "ensure_default_mission_templates", lambda cursor: None))
        sends = stack.enter_context(
            patch.object(httpx.Client, "send", side_effect=RuntimeError("Acceptance forbids HTTP delivery"))
        )
        if not outbound_policy.outbound_blocked():
            raise RuntimeError("Stage outbound stop must remain enabled")
        yield proxy
        if sends.call_count:
            raise RuntimeError("A service attempted HTTP delivery")


def check(value, message):
    if not value:
        raise RuntimeError(message)


def exercise(conn, club_id):
    """Call real services with disposable fixtures on an already guarded connection."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(guest_id),0)+1 AS id FROM guests")
        guest_id = int(cur.fetchone()["id"])
        cur.execute(
            "SELECT guest_id,uuid,date_start,date_stop FROM guest_sessions WHERE club_id=%s AND guest_id IS NOT NULL AND date_stop>date_start ORDER BY date_start DESC LIMIT 1",
            (club_id,),
        )
        source = cur.fetchone()
        check(source, "No imported personal session to copy into test guest")
        cur.execute("SELECT COUNT(*) AS n FROM guests WHERE club_id=%s AND phone=%s", (club_id, PHONE))
        check(cur.fetchone()["n"] == 0, "Reserved acceptance telephone is already present")
        cur.execute(
            "INSERT INTO guests (club_id,guest_id,fio,phone) VALUES (%s,%s,%s,%s)",
            (club_id, guest_id, "[ТЕСТ] Проверка наград Gizmo", PHONE),
        )
        cur.execute("SELECT COALESCE(MAX(id),0)+1 AS id FROM guest_sessions")
        session_id = int(cur.fetchone()["id"])
        cur.execute(
            "INSERT INTO guest_sessions (club_id,id,guest_id,uuid,date_start,date_stop) VALUES (%s,%s,%s,%s,%s,%s)",
            (club_id, session_id, guest_id, source["uuid"], source["date_start"], source["date_stop"]),
        )
        cur.execute("SELECT id FROM mission_templates WHERE target_metric='visits_count' LIMIT 1")
        template = cur.fetchone()
        check(template, "Visit mission template is missing")
        template_id = template["id"]
    mission_id = missions.create_club_mission(
        club_id, template_id, 1, token_reward=3, cm_bonus_reward=100, custom_name="[ТЕСТ] Один визит"
    )
    first = wheel.sync_guest_wheel_tokens(guest_id, club_id)
    check(any(m["id"] == mission_id and m["is_completed"] for m in first), "Imported visit did not complete mission")
    before = reception.get_reception_guest_lookup(club_id=club_id, phone=PHONE)
    check(
        before["guest"]["bonus_balance"] == 100 and before["guest"]["token_balance"] == 3,
        "Mission award amounts differ",
    )
    wheel.sync_guest_wheel_tokens(guest_id, club_id)
    repeat = reception.get_reception_guest_lookup(club_id=club_id, phone=PHONE)
    check(repeat["guest"]["bonus_balance"] == 100 and repeat["guest"]["token_balance"] == 3, "Mission awarded twice")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO club_cases (club_id,name,price_tokens,is_active) VALUES (%s,%s,2,1)",
            (club_id, "[ТЕСТ] Приёмка Gizmo"),
        )
        case_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO club_case_items (club_id,case_id,name,probability,is_active) VALUES (%s,%s,%s,100,1)",
            (club_id, case_id, "[ТЕСТ] Стикер"),
        )
        item_id = int(cur.lastrowid)
    opening = cases.open_case(guest_id, club_id, case_id, test_mode=True)
    check(opening["claim"], "Physical prize claim was not created")
    claim_id = opening["claim"]["id"]
    lookup = reception.get_reception_guest_lookup(club_id=club_id, phone=PHONE)
    check(lookup["guest"]["token_balance"] == 1, "Case token debit differs")
    check([r["id"] for r in lookup["prize_claims"]] == [claim_id], "Reception lost or duplicated physical prize")
    check(prize_claims.mark_prize_claim_issued_by_owner(claim_id, club_id)["ok"], "Prize could not be issued")
    check(not prize_claims.mark_prize_claim_issued_by_owner(claim_id, -1)["ok"], "Another club can issue this prize")
    with conn.cursor() as cur:
        cur.execute("UPDATE club_cases SET price_tokens=1 WHERE id=%s AND club_id=%s", (case_id, club_id))
        cur.execute("UPDATE club_case_items SET bonus_amount=25 WHERE id=%s AND club_id=%s", (item_id, club_id))
    bonus_opening = cases.open_case(guest_id, club_id, case_id, test_mode=True)
    check(not bonus_opening["claim"], "Automatic bonus prize created a physical claim")
    lookup = reception.get_reception_guest_lookup(club_id=club_id, phone=PHONE)
    check(lookup["guest"]["token_balance"] == 0 and lookup["guest"]["bonus_balance"] == 125, "Case bonus award differs")
    check(lookup["prize_claims"][0]["status"] == "issued", "Reception did not display issued status")
    redeem = cm_bonuses.redeem_cm_bonuses(dict(club_id=club_id, guest_id=guest_id), amount=50)
    check(redeem["amount"] == 50 and redeem["balance_after"] == 75, "Manual credit request debit differs")
    check(not redeem["notification_sent"], "Unexpected notification delivery")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cm_bonus_redeem_requests SET admin_chat_id=%s WHERE id=%s", ("328908187", redeem["request_id"])
        )
    # Exercise callback service only: no real Telegram callback or Gizmo credit.
    credited = cm_bonuses.mark_cm_bonus_redeem_credited_by_telegram(
        redeem["request_id"], 328908187, 328908187, "stage-acceptance"
    )
    check(credited["ok"], "Manual credit confirmation failed")
    repeat = cm_bonuses.mark_cm_bonus_redeem_credited_by_telegram(
        redeem["request_id"], 328908187, 328908187, "stage-acceptance"
    )
    check(repeat.get("already_done"), "Repeated manual confirmation was not idempotent")
    check(cm_bonuses.get_cm_bonus_balance(guest_id, club_id) == 75, "Repeated confirmation changed wallet")
    return dict(
        mission_completed=True,
        mission_reward_not_duplicated=True,
        case_token_debit=True,
        case_bonus_credit=True,
        physical_prize_visible_and_issued=True,
        cross_club_issue_rejected=True,
        manual_credit_request_idempotent=True,
        outbound_blocked=True,
        test_guest_id=guest_id,
        test_mission_id=mission_id,
        test_case_id=case_id,
        test_item_id=item_id,
    )


def run(source_club_id, *, directory=DIRECTORY):
    require_stage_environment()
    with run_lock(directory / "acceptance.lock"):
        manifest = private_json(directory / f"acceptance-{source_club_id}.json")
        club_id = int(manifest["test_club_id"])
        check(club_id != source_club_id, "Acceptance club must differ from source")
        with run_lock(directory / f"sync-{club_id}.lock"):
            credentials = private_json(directory / f"sync-{club_id}.json")
            check(credentials.get("enabled") is False, "Acceptance sync must be paused")
            conn = get_db_connection()
            report = dict(club_id=club_id, status="running", checked_at_utc=datetime.now(UTC).isoformat())
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT name,owner_id,service_enabled,integration_provider FROM clubs WHERE club_id=%s FOR UPDATE",
                        (club_id,),
                    )
                    club = cur.fetchone()
                    check(
                        club
                        and club["name"] == TEST_NAME
                        and club["owner_id"] is None
                        and club["service_enabled"] == 0
                        and club["integration_provider"] == "gizmo",
                        "Wrong acceptance club or service is enabled",
                    )
                    cur.execute("SELECT COUNT(*) AS n FROM club_missions WHERE club_id=%s", (club_id,))
                    check(cur.fetchone()["n"] == 0, "Acceptance club already has missions")
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM club_wheel_settings WHERE club_id=%s AND is_enabled=1", (club_id,)
                    )
                    check(cur.fetchone()["n"] == 0, "Acceptance club already has automatic visit rewards")
                    # Transaction rollback is only reliable on transactional tables.
                    for table in sorted(WRITE_TABLES | {"clubs"}):
                        cur.execute(
                            "SELECT ENGINE AS engine FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                            (table,),
                        )
                        row = cur.fetchone()
                        check(row and row["engine"].lower() == "innodb", f"{table}: existing InnoDB table required")
                    cur.execute("SELECT COUNT(*) AS n FROM guests WHERE club_id=%s", (club_id,))
                    guest_count = cur.fetchone()["n"]
                    # Only this uncommitted transaction sees service enabled.
                    cur.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=%s", (club_id,))
                with service_transaction(conn) as transaction:
                    report.update(exercise(transaction, club_id))
            finally:
                conn.rollback()
                conn.close()
            # Fresh connection confirms the synthetic guest did not survive.
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS n FROM guests WHERE club_id=%s", (club_id,))
                    check(cur.fetchone()["n"] == guest_count, "Guest count changed after rollback")
                    cur.execute("SELECT service_enabled FROM clubs WHERE club_id=%s", (club_id,))
                    check(cur.fetchone()["service_enabled"] == 0, "Club service changed after rollback")
                    for table in (
                        "guests",
                        "guest_sessions",
                        "guest_mission_completions",
                        "guest_case_openings",
                        "guest_prize_claims",
                        "guest_wheel_token_balances",
                        "guest_wheel_token_transactions",
                        "cm_bonus_balances",
                        "cm_bonus_transactions",
                        "cm_bonus_redeem_requests",
                    ):
                        cur.execute(
                            f"SELECT COUNT(*) AS n FROM {table} WHERE club_id=%s AND guest_id=%s",
                            (club_id, report["test_guest_id"]),
                        )
                        check(cur.fetchone()["n"] == 0, f"Test rows survived in {table}")
                with conn.cursor() as cur:
                    for table, field in (
                        ("club_missions", "test_mission_id"),
                        ("club_cases", "test_case_id"),
                        ("club_case_items", "test_item_id"),
                    ):
                        cur.execute(
                            f"SELECT COUNT(*) AS n FROM {table} WHERE club_id=%s AND id=%s", (club_id, report[field])
                        )
                        check(cur.fetchone()["n"] == 0, f"Test configuration survived in {table}")
                report.update(
                    status="complete",
                    test_rows_rolled_back=True,
                    limitation="Service-level single-transaction test; no real Telegram delivery, web authorization or Gizmo balance write",
                )
            finally:
                conn.close()
            return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-club-id", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source_club_id), ensure_ascii=False, indent=2))
