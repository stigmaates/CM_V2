"""Read-only prerequisite check for real stage administrator buttons.

Does not send messages, poll updates, start a bot, or change any database row.
Only the explicitly authorized private account @stigmaates is queried.
"""

import json
import logging
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import BOT_TOKEN, CM_BONUS_BOT_TOKEN, CM_BONUS_PROXY_URL, TG_PROXY_URL
from app.integrations.stage import PRODUCTION_ENV, require_stage_environment
from scripts.check_gizmo_stage_telegram import verify_recipient

RECIPIENT = 328908187


def api(client, method, payload):
    if (method, payload) not in (("getMe", {}), ("getChat", {"chat_id": RECIPIENT})):
        raise ValueError("Only read-only bot and authorized-recipient checks are allowed")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        response = client.post(f"https://api.telegram.org/bot{CM_BONUS_BOT_TOKEN}/{method}", json=payload)
        data = response.json()
        if response.status_code == 200 and data.get("ok"):
            return data.get("result")
    except (httpx.HTTPError, ValueError):
        pass  # Never expose an exception containing the bot token URL.
    return None


def run():
    require_stage_environment()
    prod = dotenv_values(PRODUCTION_ENV)
    prod_tokens = {str(prod.get(name) or "").strip() for name in ("BOT_TOKEN", "CM_BONUS_BOT_TOKEN")}
    token = str(CM_BONUS_BOT_TOKEN or "").strip()
    if "" in prod_tokens or not token or token in prod_tokens or token == str(BOT_TOKEN or "").strip():
        return dict(
            status="separate_admin_bot_required",
            message="Нужен отдельный администраторский бот стейджа. Сообщения не отправлялись.",
        )
    with httpx.Client(timeout=15, proxy=CM_BONUS_PROXY_URL or TG_PROXY_URL or None) as client:
        me = api(client, "getMe", {})
        if not me or not me.get("is_bot") or not me.get("username"):
            return dict(status="bot_not_verified", message="Не удалось проверить администраторского бота стейджа.")
        chat = api(client, "getChat", {"chat_id": RECIPIENT})
    verified = verify_recipient(chat, RECIPIENT)
    return dict(
        status="ready_for_callback_setup" if verified else "needs_start",
        bot_username=me["username"],
        bot_link=f"https://t.me/{me['username']}",
        authorized_recipient="@stigmaates",
        read_only=True,
        message=(
            "Адресат подтверждён; можно готовить тест кнопок."
            if verified
            else "Откройте этого бота и нажмите Старт с аккаунта @stigmaates."
        ),
        limitation="Read-only bot/recipient check; no callback tested and no messages sent",
    )


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print("Проверка остановлена: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
