"""Prepare only the ownerless stage acceptance club for @stigmaates login.

This intentionally retains a synthetic guest for a human browser test. `finish`
turns service off, pauses sync and revokes that guest's login links. Source Next
and production are never modified. Automatic outbound remains blocked.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_lifecycle import read_club, set_service
from app.integrations.gizmo_onboarding import pause_sync, queue_setup
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, run_lock, synchronize
from app.integrations.stage import PRODUCTION_ENV, require_stage_environment
from app.services.guest_auth import ensure_guest_login_tokens_club_column
from scripts import check_gizmo_stage_telegram as telegram
from scripts.verify_gizmo_stage_lifecycle import TEST_NAME

CLUB = 900002
GUEST = 900900002
RECIPIENT = 328908187
NAME = "Тестовый гость · проверка входа Gizmo"


def verify_bot():
    prod = str(dotenv_values(PRODUCTION_ENV).get("BOT_TOKEN") or "").strip()
    if not prod or not telegram.BOT_TOKEN or prod == telegram.BOT_TOKEN:
        raise ValueError("Нужен отдельный стейдж-бот.")
    with httpx.Client(timeout=15, proxy=telegram.TG_PROXY_URL or None) as client:
        me = telegram.api(client, "getMe", {})
        if not me or me.get("username") != "cyberbonus_test_bot":
            raise ValueError("Имя тестового бота не подтверждено.")
        if not telegram.verify_recipient(telegram.api(client, "getChat", {"chat_id": RECIPIENT}), RECIPIENT):
            raise ValueError("Тестовый адресат @stigmaates не подтверждён.")


def verify_target(conn, directory):
    manifest = private_json(directory / "acceptance-900001.json")
    club = read_club(conn, CLUB)
    if (
        manifest.get("test_club_id") != CLUB
        or not club
        or club.get("name") != TEST_NAME
        or club.get("owner_id") is not None
        or club.get("integration_provider") != "gizmo"
        or not club.get("integration_ready")
    ):
        raise ValueError("Не подтверждён отдельный тестовый клуб. Ничего не изменено.")
    with conn.cursor() as cur:
        cur.execute("SELECT guest_id, telegram_id FROM guests WHERE club_id=%s AND telegram_id IS NOT NULL", (CLUB,))
        for row in cur.fetchall():
            if int(row["guest_id"]) != GUEST or int(row["telegram_id"]) != RECIPIENT:
                raise ValueError("У тестового клуба есть другой Telegram-адресат. Подготовка остановлена.")
        cur.execute("SELECT fio, telegram_id FROM guests WHERE club_id=%s AND guest_id=%s", (CLUB, GUEST))
        guest = cur.fetchone()
        if guest and guest.get("fio") != NAME:
            raise ValueError("ID тестового гостя уже занят другой карточкой.")
    conn.rollback()


def finish(conn, directory):
    set_service(conn, CLUB, False, directory=directory)
    pause_sync(conn, CLUB, directory=directory)
    with conn.cursor() as cur:
        ensure_guest_login_tokens_club_column(cur)
        cur.execute(
            "SELECT COUNT(*) AS n FROM guest_login_tokens WHERE club_id=%s AND guest_id=%s AND telegram_id=%s AND is_confirmed=1",
            (CLUB, GUEST, RECIPIENT),
        )
        confirmations = int(cur.fetchone()["n"])
        cur.execute(
            "UPDATE guest_login_tokens SET is_confirmed=0, expires_at=UTC_TIMESTAMP() WHERE club_id=%s", (CLUB,)
        )
        cur.execute(
            "UPDATE guests SET telegram_id=NULL WHERE club_id=%s AND guest_id=%s AND telegram_id=%s",
            (CLUB, GUEST, RECIPIENT),
        )
    conn.commit()
    return dict(status="closed", confirmed_bot_logins=confirmations, service_enabled=False, sync_paused=True)


def run(action, *, directory=DIRECTORY):
    require_stage_environment()
    conn = get_db_connection()
    try:
        with run_lock(directory / "acceptance.lock"):
            verify_target(conn, directory)
            if action == "finish":
                report = finish(conn, directory)
            else:
                verify_bot()  # Read-only Telegram calls; no new messages sent.
                # Reject repeats while a human is already testing.
                if read_club(conn, CLUB).get("service_enabled"):
                    raise ValueError("Тест уже подготовлен. Используйте ссылку входа или команду finish.")
                try:
                    credentials = private_json(directory / f"sync-{CLUB}.json")
                    queue_setup(conn, CLUB, credentials["connection"], directory=directory)
                    print("Обновляем историю отдельного тестового клуба…", flush=True)
                    if synchronize(conn, CLUB, directory=directory).get("status") != "complete":
                        raise ValueError("История тестового клуба не обновилась.")
                    verify_target(conn, directory)
                    now = datetime.now(UTC).replace(tzinfo=None)
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO guests (club_id,guest_id,fio,phone,telegram_id,created_at,date_insert) VALUES (%s,%s,%s,NULL,%s,%s,%s) ON DUPLICATE KEY UPDATE telegram_id=VALUES(telegram_id)",
                            (CLUB, GUEST, NAME, RECIPIENT, now, now),
                        )
                    conn.commit()
                    set_service(conn, CLUB, True, directory=directory)
                    # Stable isolated fixture; updates are unnecessary during a login check.
                    pause_sync(conn, CLUB, directory=directory)
                    report = dict(
                        status="ready_for_browser",
                        service_enabled=True,
                        sync_paused=True,
                        login_url=f"https://stage.cyber-bonus.ru/guest/login?club_id={CLUB}",
                        authorized_recipient="@stigmaates",
                        guest_id=GUEST,
                        limitation="Tests login of a prelinked synthetic guest; not contact/phone matching or a queued campaign",
                    )
                except BaseException:
                    conn.rollback()
                    finish(conn, directory)
                    raise
            report.update(club_id=CLUB, checked_at_utc=datetime.now(UTC).isoformat())
            atomic_json(directory / "guest-login-acceptance.json", report)
            return report
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.action), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            str(exc) if isinstance(exc, ValueError) else "Проверка остановлена: " + type(exc).__name__, file=sys.stderr
        )
        raise SystemExit(1)
