"""Send one explicitly authorized test message to @stigmaates from the stage bot.

Does not change club flags or Telegram bindings, consume getUpdates, start a
poller, or enable outbound delivery in other processes. Does not test login.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import BOT_TOKEN, BOT_USERNAME, TG_PROXY_URL
from app.core import get_db_connection
from app.integrations.stage import PRODUCTION_ENV, require_stage_environment
from app.services.outbound_policy import allow_manual_mailing_outbound
from scripts import process_mailings

USERNAME = "stigmaates"
TEXT = (
    "Тест Cyber Bonus · Gizmo\n\n"
    "Проверяем доставку сообщения со стейджа на ваш тестовый аккаунт. "
    "Это проверка канала рассылок; бонусы и баланс клуба не изменены."
)


def api(client, method, payload):
    # Application imports can enable INFO globally. HTTP request URLs contain
    # the bot token, so suppress HTTP client diagnostics before every call.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        response = client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload)
        data = response.json()
        if response.status_code != 200 or not data.get("ok"):
            return None
        return data["result"]
    except (httpx.HTTPError, ValueError, KeyError):
        return None  # Never print an exception containing the bot token URL.


def verify_recipient(chat, telegram_id):
    return bool(
        chat
        and chat.get("type") == "private"
        and chat.get("id") == telegram_id
        and str(chat.get("username") or "").casefold() == USERNAME
    )


def run(telegram_id=None):
    require_stage_environment()
    production_token = str(dotenv_values(PRODUCTION_ENV).get("BOT_TOKEN") or "").strip()
    if not production_token or not BOT_TOKEN or BOT_TOKEN == production_token:
        raise ValueError("Нужен отдельный токен стейдж-бота; прод-бот не использован.")
    if process_mailings.BOT_TOKEN != BOT_TOKEN:
        raise ValueError("Настройки отправщика отличаются от стейдж-бота.")
    with httpx.Client(timeout=15, proxy=TG_PROXY_URL or None) as client:
        me = api(client, "getMe", {})
        if not me or str(me.get("username") or "").casefold() != str(BOT_USERNAME or "").lstrip("@").casefold():
            raise ValueError("Не удалось подтвердить имя стейдж-бота по getMe.")
        report = dict(
            bot_username=me["username"], bot_link=f"https://t.me/{me['username']}", authorized_recipient="@" + USERNAME
        )
        if telegram_id is None:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    # Previously confirmed user-created test guest; never enumerate real guests.
                    cur.execute("SELECT telegram_id FROM guests WHERE club_id=%s AND guest_id=%s", (900001, 900900001))
                    row = cur.fetchone()
                    telegram_id = int(row["telegram_id"]) if row and row.get("telegram_id") else None
            finally:
                conn.close()
        if not telegram_id or telegram_id <= 0:
            return dict(
                report,
                status="needs_telegram_id",
                message="Откройте стейдж-бота, нажмите Старт и пришлите свой числовой Telegram ID. Сообщения пока не отправлялись.",
            )
        chat = api(client, "getChat", {"chat_id": telegram_id})
        if not verify_recipient(chat, telegram_id):
            return dict(
                report,
                status="recipient_not_verified",
                message="Адресат @stigmaates не подтверждён. Нажмите Старт в стейдж-боте и проверьте числовой Telegram ID. Сообщения не отправлялись.",
            )
        # Process-local manual override; the checkout stop marker stays in place.
        with patch.dict(os.environ, {"ALLOW_STAGE_MANUAL_MAILINGS": "1"}), allow_manual_mailing_outbound():
            try:
                response = process_mailings.send_single_message(telegram_id, TEXT, "HTML", [])
                data = response.json()
            except (httpx.HTTPError, ValueError):
                return dict(
                    report,
                    status="delivery_unknown",
                    message="Не удалось получить ответ; проверьте Telegram перед повтором.",
                )
        if response.status_code != 200 or not data.get("ok"):
            return dict(report, status="delivery_failed", telegram_error_code=data.get("error_code"))
        return dict(
            report,
            status="sent",
            message_id=data["result"]["message_id"],
            limitation="Transport delivery only; guest login, queued campaign and admin callback not exercised",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram-id", type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.telegram_id), ensure_ascii=False, indent=2))
    except Exception as exc:
        # Configuration errors above contain no secrets; network traces must not escape.
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        else:
            print("Проверка остановлена: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
