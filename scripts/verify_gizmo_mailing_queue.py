"""Real stage queue acceptance, restricted to one authorized Telegram recipient.

Uses only the disabled, ownerless acceptance club and synthetic guest. Sync
stays paused; its service flag is temporarily enabled as a test fixture, not
through onboarding. Queue, worker and transport are real. The owner UI and
administrator callbacks are not exercised. A persisted attempt prevents
blind retries after a network timeout. No rewards or source data are changed.
"""

import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, run_lock
from app.integrations.stage import require_stage_environment
from app.services.mailing import create_mailing_for_recipients
from app.services.outbound_policy import allow_manual_mailing_outbound
from scripts import process_mailings as worker
from scripts.prepare_gizmo_stage_login import CLUB, GUEST, NAME, RECIPIENT, verify_bot, verify_target

TEXT = (
    "Тест Cyber Bonus · очередь CRM\n\n"
    "Сообщение прошло через обычную очередь рассылок. "
    "При выключенном обслуживании отправка была остановлена; после включения — выполнена. "
    "Повторный запуск проверит отсутствие второй отправки. Балансы и награды не изменены."
)


def snapshot(conn, mailing_id):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,success_count,failed_count FROM mailings WHERE id=%s AND club_id=%s", (mailing_id, CLUB)
        )
        result = dict(cur.fetchone() or {})
        cur.execute(
            "SELECT guest_id,telegram_id,status FROM mailing_recipients WHERE mailing_id=%s ORDER BY id", (mailing_id,)
        )
        result["recipients"] = cur.fetchall()
    conn.rollback()
    return result


def fixture_service(conn, enabled):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT name,owner_id,integration_provider FROM clubs WHERE club_id=%s FOR UPDATE", (CLUB,))
        row = cur.fetchone()
        from scripts.verify_gizmo_stage_lifecycle import TEST_NAME

        if not row or row["name"] != TEST_NAME or row["owner_id"] is not None or row["integration_provider"] != "gizmo":
            raise ValueError("Изменилась принадлежность тестового клуба.")
        cur.execute("UPDATE clubs SET service_enabled=%s WHERE club_id=%s", (int(enabled), CLUB))
    conn.commit()


def run(*, directory=DIRECTORY):
    require_stage_environment()
    path = directory / "mailing-queue-acceptance.json"
    conn = get_db_connection()
    try:
        with run_lock(directory / "acceptance.lock"), run_lock(directory / f"sync-{CLUB}.lock"):
            verify_target(conn, directory)
            credentials = private_json(directory / f"sync-{CLUB}.json")
            with conn.cursor() as cur:
                cur.execute("SELECT service_enabled FROM clubs WHERE club_id=%s", (CLUB,))
                enabled = cur.fetchone()["service_enabled"]
                cur.execute("SELECT fio,telegram_id FROM guests WHERE club_id=%s AND guest_id=%s", (CLUB, GUEST))
                guest = cur.fetchone()
            conn.rollback()
            if enabled or credentials.get("enabled") or not guest or guest["fio"] != NAME or guest.get("telegram_id"):
                raise ValueError(
                    "Сначала завершите тест входа: клуб и обновления должны быть выключены, Telegram отвязан."
                )
            if path.exists():
                previous = private_json(path)
                if previous.get("status") == "complete":
                    return dict(previous, reused_report=True)
                raise ValueError(
                    "Предыдущая попытка уже есть. Проверьте её результат; автоматической повторной отправки не будет."
                )
            verify_bot()
            from scripts.check_gizmo_stage_telegram import BOT_TOKEN

            if worker.BOT_TOKEN != BOT_TOKEN:
                raise ValueError("Отправщик отличается от проверенного стейдж-бота.")
            report = dict(
                status="running", club_id=CLUB, recipient="@stigmaates", started_at_utc=datetime.now(UTC).isoformat()
            )
            atomic_json(path, report)
            mailing_id = None
            attempts = 0
            actual_request = worker.tg_request

            def restricted_request(method, payload=None, files=None):
                nonlocal attempts
                if (
                    method != "sendMessage"
                    or files
                    or not payload
                    or payload.get("chat_id") != RECIPIENT
                    or payload.get("text") != TEXT
                    or attempts
                ):
                    raise ValueError("Запрещена отправка вне единственного тестового сообщения.")
                attempts += 1
                # Persist before contacting Telegram: timeout must never cause a blind resend.
                report["delivery_attempted"] = True
                atomic_json(path, report)
                try:
                    response = actual_request(method, payload, files)
                except httpx.HTTPError as exc:
                    raise ValueError("Ответ Telegram не получен: " + type(exc).__name__) from None
                if response.status_code == 200:
                    data = response.json()
                    report["telegram_message_id"] = (data.get("result") or {}).get("message_id")
                return response

            try:
                with (
                    patch.dict(os.environ, {"ALLOW_STAGE_MANUAL_MAILINGS": "1"}),
                    allow_manual_mailing_outbound(),
                    patch.object(worker, "tg_request", restricted_request),
                ):
                    created = create_mailing_for_recipients(
                        conn,
                        CLUB,
                        [{"guest_id": GUEST, "telegram_id": RECIPIENT}],
                        TEXT,
                        filters_json={"stage_acceptance": "gizmo_queue", "authorized_recipient": "stigmaates"},
                    )
                    mailing_id = created["mailing_id"]
                    conn.commit()
                    report["mailing_id"] = mailing_id
                    atomic_json(path, report)
                    worker.process_one_mailing(conn, mailing_id)
                    paused = snapshot(conn, mailing_id)
                    if (
                        attempts
                        or paused.get("status") != "queued"
                        or [r["status"] for r in paused["recipients"]] != ["pending"]
                    ):
                        raise ValueError("Проверка остановки очереди при выключенном обслуживании не пройдена.")
                    report["disabled_blocks_delivery"] = True
                    fixture_service(conn, True)
                    worker.process_one_mailing(conn, mailing_id)
                    delivered = snapshot(conn, mailing_id)
                    if (
                        attempts != 1
                        or delivered.get("status") != "completed"
                        or [r["status"] for r in delivered["recipients"]] != ["sent"]
                    ):
                        raise ValueError("Отправка через очередь не подтверждена. Повторять автоматически нельзя.")
                    report["queue_delivery_confirmed"] = True
                    # Completed job and a requeued job must both skip already-sent recipients.
                    worker.process_one_mailing(conn, mailing_id)
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE mailings SET status='queued' WHERE id=%s AND club_id=%s", (mailing_id, CLUB)
                        )
                    conn.commit()
                    worker.process_one_mailing(conn, mailing_id)
                    if attempts != 1 or snapshot(conn, mailing_id) != delivered:
                        raise ValueError("Повторная обработка изменила результат отправки.")
                    report.update(status="complete", retry_did_not_resend=True)
            except BaseException as exc:
                report.update(status="error", error_type=type(exc).__name__)
                raise
            finally:
                conn.rollback()
                fixture_service(conn, False)
                if mailing_id is not None:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE mailing_recipients SET status='failed',error_text='Stage acceptance closed' WHERE mailing_id=%s AND status='pending'",
                            (mailing_id,),
                        )
                        cur.execute(
                            "UPDATE mailings SET status='completed',finished_at=NOW(),success_count=(SELECT COUNT(*) FROM mailing_recipients WHERE mailing_id=%s AND status='sent'),failed_count=(SELECT COUNT(*) FROM mailing_recipients WHERE mailing_id=%s AND status='failed') WHERE id=%s AND club_id=%s",
                            (mailing_id, mailing_id, mailing_id, CLUB),
                        )
                    conn.commit()
                report.update(
                    service_enabled=False,
                    sync_paused=True,
                    finished_at_utc=datetime.now(UTC).isoformat(),
                    limitation="Queue/worker/Telegram transport; not owner UI, admin callbacks or crash-safe exactly-once delivery",
                )
                atomic_json(path, report)
            return report
    finally:
        conn.close()


if __name__ == "__main__":

    def stop_requested(signum, frame):
        raise KeyboardInterrupt("Проверка прервана")

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop_requested)
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            str(exc) if isinstance(exc, ValueError) else "Проверка остановлена: " + type(exc).__name__, file=sys.stderr
        )
        raise SystemExit(1)
