import logging
import re

from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes
from telegram.request import HTTPXRequest

from app.config import CM_BONUS_BOT_TOKEN, TG_PROXY_URL
from app.services.prize_claims import (
    format_prize_claim_message,
    mark_prize_claim_issued_by_telegram,
)
from app.services.cm_bonuses import (
    format_cm_bonus_redeem_message,
    mark_cm_bonus_redeem_credited_by_telegram,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


async def prize_claim_issued_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button ✅ Приз выдан from the admin chat bot."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    match = re.match(r"^prize_claim_issued:(\d+)$", data)
    if not match:
        await query.answer("Некорректная кнопка", show_alert=True)
        return

    claim_id = int(match.group(1))
    user = update.effective_user
    chat = update.effective_chat

    if user:
        username = f"@{user.username}" if user.username else user.full_name
    else:
        username = None

    logging.info(
        "PRIZE CLAIM BUTTON: claim_id=%s chat_id=%s user_id=%s username=%s",
        claim_id,
        chat.id if chat else None,
        user.id if user else None,
        username,
    )

    try:
        result = mark_prize_claim_issued_by_telegram(
            claim_id=claim_id,
            chat_id=chat.id if chat else None,
            telegram_id=user.id if user else None,
            username=username,
        )
    except Exception as e:
        logging.exception("Ошибка при выдаче приза через кнопку #%s", claim_id)
        await query.answer(f"Ошибка: {e}", show_alert=True)
        return

    if not result.get("ok"):
        await query.answer(result.get("message") or f"Не удалось закрыть заявку #{claim_id}", show_alert=True)
        return

    claim = result.get("claim") or {}
    text = format_prize_claim_message(claim, issued=True)

    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=None,
        )
    except Exception:
        logging.exception("Не удалось обновить сообщение заявки #%s", claim_id)

    if result.get("already_done"):
        await query.answer(f"Заявка #{claim_id} уже была выдана", show_alert=False)
    else:
        await query.answer(f"Приз #{claim_id} отмечен как выдан", show_alert=False)


async def cm_bonus_credited_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button ✅ Бонусы зачислены from the admin chat bot."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    match = re.match(r"^cm_bonus_credited:(\d+)$", data)
    if not match:
        await query.answer("Некорректная кнопка", show_alert=True)
        return

    request_id = int(match.group(1))
    user = update.effective_user
    chat = update.effective_chat

    if user:
        username = f"@{user.username}" if user.username else user.full_name
    else:
        username = None

    logging.info(
        "CM BONUS BUTTON: request_id=%s chat_id=%s user_id=%s username=%s",
        request_id,
        chat.id if chat else None,
        user.id if user else None,
        username,
    )

    try:
        result = mark_cm_bonus_redeem_credited_by_telegram(
            request_id=request_id,
            chat_id=chat.id if chat else None,
            telegram_id=user.id if user else None,
            username=username,
        )
    except Exception as e:
        logging.exception("Ошибка при закрытии заявки КБ через кнопку #%s", request_id)
        await query.answer(f"Ошибка: {e}", show_alert=True)
        return

    if not result.get("ok"):
        await query.answer(result.get("message") or f"Не удалось закрыть заявку КБ #{request_id}", show_alert=True)
        return

    redeem_request = result.get("request") or {}
    text = format_cm_bonus_redeem_message(redeem_request, credited=True)

    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=None,
        )
    except Exception:
        logging.exception("Не удалось обновить сообщение заявки КБ #%s", request_id)

    if result.get("already_done"):
        await query.answer(f"Заявка КБ #{request_id} уже была закрыта", show_alert=False)
    else:
        await query.answer(f"КБ по заявке #{request_id} отмечены как зачисленные", show_alert=False)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Ошибка в админском боте:", exc_info=context.error)


def main():
    token = (CM_BONUS_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("CM_BONUS_BOT_TOKEN is empty. Admin bot cannot start.")

    builder = ApplicationBuilder().token(token)

    if TG_PROXY_URL:
        request = HTTPXRequest(
            proxy_url=TG_PROXY_URL,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0,
        )

        get_updates_request = HTTPXRequest(
            proxy_url=TG_PROXY_URL,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0,
        )

        builder = builder.request(request).get_updates_request(get_updates_request)
    else:
        builder = (
            builder
            .get_updates_connect_timeout(30.0)
            .get_updates_read_timeout(30.0)
            .get_updates_pool_timeout(30.0)
        )

    app = builder.build()
    app.add_handler(CallbackQueryHandler(prize_claim_issued_callback, pattern=r"^prize_claim_issued:\d+$"))
    app.add_handler(CallbackQueryHandler(cm_bonus_credited_callback, pattern=r"^cm_bonus_credited:\d+$"))
    app.add_error_handler(error_handler)

    logging.info("Admin Telegram bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
