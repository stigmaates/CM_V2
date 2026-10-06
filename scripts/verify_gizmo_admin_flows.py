"""Stage service acceptance for phone links, admin approvals and paused rewards.

All fixture writes, including service flags, live in one transaction and are
rolled back. No messages are sent. This is not a real Telegram button/UI test
or a concurrent-transaction test. Auto-increment counters may advance.
"""

import json
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_sync import DIRECTORY, private_json, run_lock
from app.integrations.stage import require_stage_environment
from app.services import (
    cm_bonuses,
    wheel,
)
from app.services import (
    first_visit_survey as surveys,
)
from app.services import (
    telegram_links as links,
)
from app.services import (
    topup_bonuses as topups,
)
from app.services.club_service import ClubServiceDisabled
from bot import main as guest_bot
from scripts import verify_gizmo_reward_journey as guard
from scripts.verify_gizmo_stage_lifecycle import TEST_NAME

TABLES = {
    "clubs",
    "guests",
    "guest_balance_topups",
    "club_topup_bonus_settings",
    "guest_topup_bonus_awards",
    "guest_telegram_link_requests",
    "first_visit_surveys",
    "cm_bonus_balances",
    "cm_bonus_transactions",
    "guest_wheel_token_balances",
    "guest_wheel_token_transactions",
}
PHONE = "70000000009"
TG = 328908187


class Transaction:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return guard.GuardedCursor(self.conn.cursor())

    def begin(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass

    def rollback(self):
        with self.conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT acceptance_action")

    def call(self, fn, *args, **kwargs):
        with self.conn.cursor() as cur:
            cur.execute("SAVEPOINT acceptance_action")
        return fn(*args, **kwargs)


def exercise(conn, club_id):
    check = guard.check
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(guest_id),0)+1 AS id FROM guests")
        guest_id = int(cur.fetchone()["id"])
        now = datetime.now(UTC).replace(tzinfo=None)
        cur.execute("UPDATE clubs SET service_enabled=1,cm_bonus_admin_chat_id=%s WHERE club_id=%s", (str(TG), club_id))
        cur.execute(
            "INSERT INTO guests(club_id,guest_id,fio,phone,created_at,date_insert) VALUES (%s,%s,%s,%s,%s,%s)",
            (club_id, guest_id, "[ТЕСТ] Проверка привязки Gizmo", PHONE, now, now),
        )
    found, count = conn.call(guest_bot.find_guest_by_phone, "8 (000) 000-00-09", club_id)
    check(count == 1 and found["guest_id"] == guest_id, "Phone lookup did not find the synthetic guest")
    conn.call(links.bind_verified_contact, guest_id, club_id, TG, expected_phone=PHONE)
    check(conn.call(links.find_linked_guest, club_id, TG)["guest_id"] == guest_id, "Verified contact did not bind")
    with conn.cursor() as cur:
        cur.execute("UPDATE guests SET telegram_id=NULL WHERE club_id=%s AND guest_id=%s", (club_id, guest_id))
    request_id = conn.call(links.create_link_request, club_id, guest_id, TG, "70000000008", PHONE, TG)
    try:
        conn.call(links.review_link_request, request_id, -999, TG, True)
    except ValueError:
        pass
    else:
        raise RuntimeError("Another chat approved phone link")
    with conn.cursor() as cur:
        cur.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=%s", (club_id,))
    try:
        conn.call(links.review_link_request, request_id, TG, TG, True)
    except ClubServiceDisabled:
        pass
    else:
        raise RuntimeError("Disabled club approved phone link")
    with conn.cursor() as cur:
        cur.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=%s", (club_id,))
    conn.call(links.review_link_request, request_id, TG, TG, True)
    check(conn.call(links.find_linked_guest, club_id, TG)["guest_id"] == guest_id, "Admin phone approval did not bind")
    try:
        conn.call(links.review_link_request, request_id, TG, TG, True)
    except ValueError:
        pass
    else:
        raise RuntimeError("Repeated phone approval was accepted")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO club_topup_bonus_settings(club_id,message_template) VALUES (%s,%s) ON DUPLICATE KEY UPDATE message_template=VALUES(message_template)",
            (club_id, "Тест: {reward_amount}"),
        )
        cur.execute(
            "INSERT INTO guest_balance_topups(club_id,topup_id,guest_id,amount,topup_at) VALUES (%s,%s,%s,1000,%s)",
            (club_id, -guest_id, guest_id, now),
        )
        cur.execute(
            "INSERT INTO guest_topup_bonus_awards(club_id,topup_id,guest_id,rule_id,topup_amount,rule_min_amount,bonus_amount,reward_type,status,delivery_status) VALUES (%s,%s,%s,0,1000,1000,25,'cm_bonus','pending_approval','waiting_approval')",
            (club_id, -guest_id, guest_id),
        )
        award_id = cur.lastrowid
        cur.execute(
            "INSERT INTO first_visit_surveys(club_id,guest_id,telegram_id,status,rating,bonus_amount) VALUES (%s,%s,%s,'awaiting_feedback',5,100)",
            (club_id, guest_id, TG),
        )
        survey_id = cur.lastrowid
        cur.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=%s", (club_id,))
    approval = dict(award_id=award_id, chat_id=TG, telegram_id=TG, telegram_username="stigmaates", approve=True)
    check(
        conn.call(topups.review_topup_bonus_award_by_telegram, **approval).get("code") == "service_disabled",
        "Disabled topup approval awarded",
    )
    check(
        conn.call(surveys.complete_survey_and_award, conn, survey_id, "Тест").get("code") == "service_disabled",
        "Disabled survey awarded",
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM cm_bonus_transactions WHERE club_id=%s AND guest_id=%s", (club_id, guest_id)
        )
        check(cur.fetchone()["n"] == 0, "Paused awards changed ledger")
        cur.execute("UPDATE clubs SET service_enabled=1 WHERE club_id=%s", (club_id,))
    check(
        not conn.call(topups.review_topup_bonus_award_by_telegram, **dict(approval, chat_id=-999))["ok"],
        "Wrong chat approved topup",
    )
    check(conn.call(topups.review_topup_bonus_award_by_telegram, **approval)["ok"], "Topup approval failed")
    check(not conn.call(topups.review_topup_bonus_award_by_telegram, **approval)["ok"], "Repeated approval accepted")
    check(conn.call(surveys.complete_survey_and_award, conn, survey_id, "Тест")["awarded"], "Survey award failed")
    check(
        conn.call(surveys.complete_survey_and_award, conn, survey_id, "Тест")["already_done"],
        "Survey retry not idempotent",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT balance FROM cm_bonus_balances WHERE club_id=%s AND guest_id=%s", (club_id, guest_id))
        check(cur.fetchone()["balance"] == 125, "Combined wallet differs or reward duplicated")
    return dict(
        phone_contact_link=True,
        phone_admin_approval=True,
        wrong_admin_chat_rejected=True,
        disabled_link_approval_blocked=True,
        disabled_topup_award_blocked=True,
        disabled_survey_award_blocked=True,
        topup_approval_not_duplicated=True,
        survey_award_not_duplicated=True,
    )


def totals(conn, club_id):
    result = {}
    with conn.cursor() as cur:
        for table in sorted(TABLES):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE club_id=%s", (club_id,))
            result[table] = cur.fetchone()["n"]
        cur.execute("SELECT * FROM clubs WHERE club_id=%s", (club_id,))
        result["club"] = cur.fetchone()
    return result


def run(*, directory=DIRECTORY):
    require_stage_environment()
    club_id = 900002
    with run_lock(directory / "acceptance.lock"), run_lock(directory / f"sync-{club_id}.lock"):
        guard.check(private_json(directory / "acceptance-900001.json")["test_club_id"] == club_id, "Wrong test club")
        guard.check(private_json(directory / f"sync-{club_id}.json").get("enabled") is False, "Sync must be paused")
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM clubs WHERE club_id=%s FOR UPDATE", (club_id,))
                club = cur.fetchone()
                guard.check(
                    club
                    and club["name"] == TEST_NAME
                    and club["owner_id"] is None
                    and club["service_enabled"] == 0
                    and club["integration_provider"] == "gizmo",
                    "Wrong or enabled test club",
                )
                cur.execute("SELECT COUNT(*) AS n FROM guests WHERE club_id=%s AND telegram_id IS NOT NULL", (club_id,))
                guard.check(cur.fetchone()["n"] == 0, "Finish live login first")
                for table in sorted(TABLES):
                    cur.execute(
                        "SELECT ENGINE AS engine FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                        (table,),
                    )
                    row = cur.fetchone()
                    guard.check(row and row["engine"].lower() == "innodb", f"{table}: InnoDB required")
            before = totals(conn, club_id)
            with ExitStack() as stack:
                proxy = Transaction(conn)
                stack.enter_context(patch.object(guard, "WRITE_TABLES", TABLES))
                for module in (links, topups, cm_bonuses, wheel, guest_bot):
                    stack.enter_context(patch.object(module, "get_db_connection", lambda: proxy))
                stack.enter_context(patch.object(cm_bonuses, "_cm_bonus_tables_ready", True))
                stack.enter_context(patch.object(wheel, "_token_tables_ready", True))
                stack.enter_context(patch.object(surveys, "ensure_first_visit_survey_tables", lambda cur: None))
                sends = stack.enter_context(
                    patch.object(httpx.Client, "send", side_effect=RuntimeError("HTTP forbidden during test"))
                )
                result = exercise(proxy, club_id)
                guard.check(not sends.call_count, "Unexpected HTTP call")
        finally:
            conn.rollback()
            conn.close()
        conn = get_db_connection()
        try:
            guard.check(totals(conn, club_id) == before, "Test rows or service flag survived rollback")
        finally:
            conn.close()
        return dict(
            status="complete",
            club_id=club_id,
            **result,
            test_rows_rolled_back=True,
            service_enabled=False,
            checked_at_utc=datetime.now(UTC).isoformat(),
            limitation="Real database services; no real Telegram callback, UI authorization or concurrent transactions",
        )


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            "Проверка остановлена: " + type(exc).__name__ + (": " + str(exc) if isinstance(exc, RuntimeError) else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)
