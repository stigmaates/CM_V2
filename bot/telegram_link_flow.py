"""Private guest conversation for administrator-reviewed phone mismatch."""

import logging
import secrets
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.request import HTTPXRequest

from app.config import BOT_TOKEN, CM_BONUS_BOT_TOKEN, CM_BONUS_PROXY_URL, TG_PROXY_URL
from app.core import get_db_connection
from app.services.rate_limit import is_rate_limited
from app.services.telegram_links import (
    HELP_MESSAGE,
    create_link_request,
    mark_notification_failed,
    review_link_request,
)


def _bot(token, proxy):
    return Bot(token=token, request=HTTPXRequest(proxy_url=proxy or None))


async def offer_phone_choices(message, context, phone):
    nonce = secrets.token_hex(8)
    context.user_data["phone_link"] = {
        "nonce": nonce,
        "token": context.user_data["guest_login_token"],
        "phone": phone,
        "step": "choice",
    }
    await message.reply_text("Ваш номер не найден в этом клубе.", reply_markup=ReplyKeyboardRemove())
    await message.reply_text(
        "Выберите подходящий вариант:",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Мой номер Telegram не совпадает с номером в LG", callback_data=f"lg_link:{nonce}:different"
                    )
                ],
                [InlineKeyboardButton("Это точно мой номер", callback_data=f"lg_link:{nonce}:help")],
            ]
        ),
    )


def _valid_state(context):
    from bot.main import get_login_token_row

    state = context.user_data.get("phone_link")
    if not state or state["token"] != context.user_data.get("guest_login_token"):
        raise ValueError("Откройте новую ссылку входа на сайте.")
    token = get_login_token_row(state["token"])
    if (
        not token
        or token.get("is_confirmed")
        or not token.get("club_id")
        or not token.get("expires_at")
        or token["expires_at"] <= datetime.utcnow()
    ):
        context.user_data.pop("phone_link", None)
        raise ValueError("Время входа истекло. Откройте новую ссылку входа на сайте.")
    return state, int(token["club_id"])


async def phone_choice_callback(update, context):
    query = update.callback_query
    if not query or not update.effective_chat or update.effective_chat.type != "private":
        return
    try:
        state, club_id = _valid_state(context)
        _, nonce, action = query.data.split(":")
        if nonce != state["nonce"]:
            raise ValueError("Эта кнопка устарела. Используйте последнее сообщение бота.")
        if action in ("help", "no"):
            context.user_data.pop("phone_link", None)
            await query.answer()
            await query.edit_message_text(HELP_MESSAGE)
            return
        if action == "different" and state["step"] == "choice":
            state["step"] = "phone"
            await query.answer()
            await query.edit_message_text("Введите номер телефона, указанный в LG, например 89270086145.")
            return
        if action != "yes" or state["step"] != "confirm":
            raise ValueError("Эта кнопка уже использована.")
        guest = state["guest"]
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT cm_bonus_admin_chat_id FROM clubs WHERE club_id = %s", (club_id,))
                chat_id = str((cur.fetchone() or {}).get("cm_bonus_admin_chat_id") or "").strip()
        finally:
            conn.close()
        if not chat_id or not CM_BONUS_BOT_TOKEN:
            raise ValueError(HELP_MESSAGE)
        request_id = create_link_request(
            club_id,
            guest["guest_id"],
            update.effective_user.id,
            state["phone"],
            guest["phone"],
            chat_id,
        )
        context.user_data.pop("phone_link", None)
        await query.answer()
        try:
            async with _bot(CM_BONUS_BOT_TOKEN, CM_BONUS_PROXY_URL or TG_PROXY_URL) as admin_bot:
                await admin_bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"Привязка Telegram · заявка №{request_id}\nКлуб: {club_id}\n"
                        f"Гость: {guest.get('fio') or 'ФИО не указано'}\n"
                        f"Номер LG: {guest['phone']}\n\n"
                        "Перед подтверждением найдите аккаунт в кабинете и проверьте личность гостя "
                        "в клубе. Попросите его показать эту заявку в своём Telegram. "
                        "Подтверждение предоставит доступ к кабинету и бонусам."
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("Подтвердить", callback_data=f"lg_review:{request_id}:yes"),
                                InlineKeyboardButton("Отклонить", callback_data=f"lg_review:{request_id}:no"),
                            ]
                        ]
                    ),
                )
        except Exception:
            logging.exception("Cannot notify admin of link request %s", request_id)
            mark_notification_failed(request_id)
            await query.edit_message_text("Не удалось отправить заявку. " + HELP_MESSAGE)
            return
        await query.edit_message_text(
            f"Заявка №{request_id} отправлена администратору клуба. Покажите ему это сообщение "
            "для проверки аккаунта.\nПосле подтверждения откройте новую ссылку входа на сайте — "
            "номер LG повторно вводить не нужно."
        )
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)


async def handle_lg_phone(update, context):
    if not context.user_data.get("phone_link"):
        return False
    if not update.effective_chat or update.effective_chat.type != "private":
        return False
    from bot.main import find_guest_by_phone, normalize_phone

    try:
        state, club_id = _valid_state(context)
        if state["step"] != "phone":
            await update.message.reply_text("Выберите вариант кнопкой в предыдущем сообщении.")
            return True
        if is_rate_limited(f"lg_lookup:{update.effective_user.id}", limit=5, window_seconds=3600):
            context.user_data.pop("phone_link", None)
            raise ValueError("Слишком много попыток поиска. " + HELP_MESSAGE)
        phone = normalize_phone(update.message.text)
        if not phone or len(phone) != 11 or not phone.startswith("7"):
            raise ValueError("Введите номер в формате 89270086145.")
        guest, count = find_guest_by_phone(phone, club_id)
        if count != 1 or not guest:
            raise ValueError("Не удалось однозначно найти аккаунт. " + HELP_MESSAGE)
        if guest.get("telegram_id") and int(guest["telegram_id"]) != update.effective_user.id:
            raise ValueError("Аккаунт уже связан с другим Telegram. " + HELP_MESSAGE)
        state["guest"] = guest
        state["step"] = "confirm"
        await update.message.reply_text(
            f"{phone}\n\n{guest.get('fio') or 'Гость'} — это ваш аккаунт?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Да", callback_data=f"lg_link:{state['nonce']}:yes"),
                        InlineKeyboardButton("Нет", callback_data=f"lg_link:{state['nonce']}:no"),
                    ]
                ]
            ),
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
    return True


async def review_callback(update, context):
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    _, request_id, decision = query.data.split(":")
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if member.status not in ("administrator", "creator"):
            raise ValueError("Подтверждать привязки может администратор Telegram-чата клуба.")
        row = review_link_request(
            int(request_id), update.effective_chat.id, update.effective_user.id, decision == "yes"
        )
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return
    await query.answer("Привязка подтверждена" if decision == "yes" else "Заявка отклонена")
    try:
        await query.edit_message_text(
            f"Привязка Telegram · заявка №{request_id}\nСтатус: {'подтверждена' if decision == 'yes' else 'отклонена'}"
        )
    except Exception:
        logging.exception("Cannot update reviewed link message %s", request_id)
    try:
        async with _bot(BOT_TOKEN, TG_PROXY_URL) as guest_bot:
            await guest_bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    "Администратор подтвердил привязку Telegram. Откройте новую ссылку входа на сайте клуба."
                    if decision == "yes"
                    else "Заявка на привязку отклонена. " + HELP_MESSAGE
                ),
            )
    except Exception:
        logging.exception("Cannot notify guest about reviewed link request %s", request_id)
