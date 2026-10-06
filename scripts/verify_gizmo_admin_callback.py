"""One real administrator button, only for the authorized stage test account.

setup persists one synthetic prize claim and sends its ordinary notification.
finish verifies the live bot's write, tests repeat confirmation and deletes only
that synthetic claim. Club settings, balances and Telegram bindings never change.
A persisted attempt prevents blind resending after an uncertain Telegram result.
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, run_lock
from app.integrations.stage import require_stage_environment
from app.services import outbound_policy, prize_claims
from scripts import check_gizmo_stage_admin_bot as probe
from scripts.prepare_gizmo_stage_login import CLUB, GUEST, NAME, RECIPIENT, verify_target

SOURCE = "stage_callback"
PRIZE = "[ТЕСТ] Проверка кнопки — ничего выдавать не нужно"
WALLETS = ("cm_bonus_balances", "cm_bonus_transactions", "guest_wheel_token_balances", "guest_wheel_token_transactions")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify_poller():
    unit = "clubmodule-stage-admin-bot.service"
    result = subprocess.run(
        ["systemctl", "show", unit, "-p", "ActiveState", "-p", "WorkingDirectory"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    check(
        values.get("ActiveState") == "active" and values.get("WorkingDirectory") == "/root/cm_stage/CM_V2",
        "Администраторский бот стейджа должен быть запущен в своей рабочей папке.",
    )


def wallet_state(conn):
    state = {}
    with conn.cursor() as cur:
        for table in WALLETS:
            cur.execute(f"SELECT * FROM {table} WHERE club_id=%s AND guest_id=%s", (CLUB, GUEST))
            # Stable, JSON-compatible representation; no other guests are read.
            state[table] = sorted(json.dumps(row, sort_keys=True, default=str) for row in cur.fetchall())
    return state


def read_claim(conn, report):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM guest_prize_claims WHERE club_id=%s AND guest_id=%s AND source_type=%s AND source_id=%s",
            (CLUB, GUEST, SOURCE, report["source_id"]),
        )
        row = cur.fetchone()
    if row:
        check(
            row["prize_name"] == PRIZE and str(row["admin_chat_id"]) == str(RECIPIENT),
            "Тестовая заявка изменилась; остановка.",
        )
    return row


def send_claim(claim_id, report, path):
    expected = prize_claims.get_prize_claim_by_id(claim_id)
    check(
        expected and expected["club_id"] == CLUB and expected["guest_id"] == GUEST and expected["prize_name"] == PRIZE,
        "Нельзя отправлять уведомление не о тестовой заявке.",
    )
    expected_text = prize_claims.format_prize_claim_message(expected)
    original_send = httpx.Client.send
    attempts = 0

    def restricted_send(client, request, *args, **kwargs):
        nonlocal attempts
        payload = json.loads(request.content)
        check(
            attempts == 0
            and request.method == "POST"
            and str(request.url) == f"https://api.telegram.org/bot{probe.CM_BONUS_BOT_TOKEN}/sendMessage"
            and str(payload.get("chat_id")) == str(RECIPIENT)
            and payload.get("text") == expected_text
            and payload.get("reply_markup")
            == {"inline_keyboard": [[{"text": "✅ Приз выдан", "callback_data": f"prize_claim_issued:{claim_id}"}]]},
            "Отправка вне единственной тестовой заявки запрещена.",
        )
        attempts += 1
        report["delivery_attempted"] = True
        atomic_json(path, report)
        try:
            return original_send(client, request, *args, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Ответ Telegram не получен; автоматического повтора не будет.") from None

    def target(club_id):
        check(int(club_id) == CLUB, "Другой клуб запрещён.")
        return str(RECIPIENT)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    check(prize_claims.CM_BONUS_BOT_TOKEN == probe.CM_BONUS_BOT_TOKEN, "Токен отправщика отличается от проверенного.")
    # Only this process and the guarded HTTP request; stop marker stays in place.
    with (
        patch.object(outbound_policy, "outbound_blocked", lambda: False),
        patch.object(prize_claims, "get_cm_bonus_admin_chat_id_for_club", target),
        patch.object(httpx.Client, "send", restricted_send),
    ):
        result = prize_claims.notify_prize_claim_admin_chat(claim_id)
    return dict(ok=bool(result.get("ok")), message_id=result.get("message_id"))


def run(action, *, directory=DIRECTORY):
    require_stage_environment()
    path = directory / "admin-callback-acceptance.json"
    with run_lock(directory / "acceptance.lock"), run_lock(directory / f"sync-{CLUB}.lock"):
        conn = get_db_connection()
        try:
            verify_target(conn, directory)
            check(
                private_json(directory / f"sync-{CLUB}.json").get("enabled") is False,
                "Обновления тестового клуба должны быть приостановлены.",
            )
            with conn.cursor() as cur:
                cur.execute("SELECT service_enabled FROM clubs WHERE club_id=%s", (CLUB,))
                check(cur.fetchone()["service_enabled"] == 0, "Обслуживание тестового клуба должно быть выключено.")
                cur.execute("SELECT fio,telegram_id FROM guests WHERE club_id=%s AND guest_id=%s", (CLUB, GUEST))
                guest = cur.fetchone()
                check(
                    guest and guest["fio"] == NAME and not guest.get("telegram_id"),
                    "Завершите тест входа перед проверкой кнопок.",
                )
            conn.rollback()
            report = private_json(path) if path.exists() else None
            if action == "setup":
                if report:
                    return dict(
                        report,
                        reused=True,
                        message="Повторной отправки нет. Нажмите кнопку в тестовом сообщении, затем запустите finish.",
                    )
                bot = probe.run()
                check(
                    bot.get("status") == "ready_for_callback_setup"
                    and bot.get("bot_username") == "cm_delivery_test_bot",
                    "Не подтверждены тестовый администраторский бот и адресат.",
                )
                verify_poller()
                report = dict(
                    status="preparing",
                    club_id=CLUB,
                    guest_id=GUEST,
                    source_id=str(uuid4()),
                    authorized_recipient="@stigmaates",
                    wallet_before=wallet_state(conn),
                    started_at_utc=datetime.now(UTC).isoformat(),
                    service_enabled=False,
                )
                atomic_json(path, report)
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO guest_prize_claims
                        (club_id,guest_id,source_type,source_id,prize_id,prize_name,prize_description,status,admin_chat_id,created_at)
                        VALUES (%s,%s,%s,%s,0,%s,%s,'pending',%s,%s)""",
                        (
                            CLUB,
                            GUEST,
                            SOURCE,
                            report["source_id"],
                            PRIZE,
                            "Проверка Cyber Bonus · Gizmo. Нажмите «Приз выдан». Это тест кнопки: реальные призы и баланс не меняются.",
                            str(RECIPIENT),
                            datetime.now(UTC).replace(tzinfo=None),
                        ),
                    )
                    report["claim_id"] = cur.lastrowid
                conn.commit()
                atomic_json(path, report)
                result = send_claim(report["claim_id"], report, path)
                report.update(
                    status="waiting_for_click" if result["ok"] else "delivery_unconfirmed",
                    message_id=result["message_id"],
                )
                atomic_json(path, report)
                return report
            check(report, "Сначала нужна setup-проверка.")
            if report["status"] in {"complete", "cancelled"}:
                return dict(report, reused=True)
            row = read_claim(conn, report)
            if action == "finish":
                if row:
                    if row["status"] != "issued":
                        return dict(
                            status="waiting_for_click",
                            claim_id=row["id"],
                            message="Нажмите «Приз выдан» в тестовом сообщении.",
                        )
                    check(
                        int(row.get("issued_by_telegram_id") or 0) == RECIPIENT and row.get("issued_at"),
                        "Выдача не подтверждена нужным Telegram-аккаунтом.",
                    )
                    repeat = prize_claims.mark_prize_claim_issued_by_telegram(
                        row["id"], RECIPIENT, RECIPIENT, "@stigmaates"
                    )
                    check(repeat.get("already_done"), "Повторное подтверждение не распознано.")
                    report.update(
                        status="verified_cleanup_pending", live_callback_verified=True, repeat_idempotent=True
                    )
                    atomic_json(path, report)
                else:
                    check(
                        report["status"] == "verified_cleanup_pending",
                        "Тестовая заявка не найдена; подтверждение кнопки не доказано.",
                    )
            conn.rollback()
            check(
                wallet_state(conn) == report["wallet_before"],
                "Баланс или операции тестового гостя изменились; требуется проверка.",
            )
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM guest_prize_claims WHERE club_id=%s AND guest_id=%s AND source_type=%s AND source_id=%s AND prize_name=%s",
                    (CLUB, GUEST, SOURCE, report["source_id"], PRIZE),
                )
            conn.commit()
            check(read_claim(conn, report) is None, "Тестовая заявка осталась после очистки.")
            report.update(
                status="complete" if action == "finish" else "cancelled",
                test_claim_removed=True,
                balances_unchanged=True,
                finished_at_utc=datetime.now(UTC).isoformat(),
                limitation="One real prize callback; no Gizmo balance write or other callback types tested",
            )
            atomic_json(path, report)
            return report
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "finish", "cancel"))
    args = parser.parse_args()
    try:
        result = run(args.action)
        result.pop("wallet_before", None)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        print(
            "Проверка остановлена: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__),
            file=sys.stderr,
        )
        raise SystemExit(1)
