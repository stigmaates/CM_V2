import logging
import re
from datetime import datetime
from telegram.request import HTTPXRequest

import pymysql
from pymysql.cursors import DictCursor

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ApplicationHandlerStop,
    CallbackQueryHandler,
)

from app.config import BOT_TOKEN, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, TG_PROXY_URL
from app.services.prize_claims import (
    mark_prize_claim_issued_by_telegram,
    format_prize_claim_message,
)
from app.services.first_visit_survey import (
    build_social_links_message,
    complete_survey_and_award,
    find_waiting_survey,
    get_survey_for_callback,
    mark_survey_started,
    save_survey_rating,
)
from app.services.wheel import award_first_authorization_token


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        ssl={"check_hostname": False}
    )




_guest_login_tokens_club_column_ready = False


def ensure_guest_login_tokens_club_column(cursor):
    global _guest_login_tokens_club_column_ready
    if _guest_login_tokens_club_column_ready:
        return

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_login_tokens'
          AND COLUMN_NAME = 'club_id'
    """)
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE guest_login_tokens
            ADD COLUMN club_id INT NULL AFTER guest_id
        """)
    _guest_login_tokens_club_column_ready = True


def normalize_phone(phone: str):
    if not phone:
        return None

    digits = re.sub(r"\D", "", phone)

    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    if len(digits) == 10:
        digits = "7" + digits

    return digits


def find_guest_by_phone(phone: str, club_id: int):
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None, 0

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT guest_id, club_id, fio, phone, telegram_id
                FROM guests
                WHERE club_id = %s
            """, (int(club_id),))
            guests = cursor.fetchall()

        matches = []

        for guest in guests:
            guest_phone_normalized = normalize_phone(guest.get("phone"))
            if guest_phone_normalized == normalized_phone:
                matches.append(guest)

        if len(matches) == 1:
            return matches[0], 1

        if len(matches) > 1:
            return None, len(matches)

        return None, 0
    finally:
        conn.close()


def bind_telegram_to_guest(guest_id: int, club_id: int, telegram_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE guests
                SET telegram_id = %s
                WHERE club_id = %s
                  AND guest_id = %s
            """, (telegram_id, club_id, guest_id))
        conn.commit()
    finally:
        conn.close()


def get_login_token_row(token: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_guest_login_tokens_club_column(cursor)
            cursor.execute("""
                SELECT token, guest_id, club_id, telegram_id, is_confirmed, created_at, expires_at
                FROM guest_login_tokens
                WHERE token = %s
                LIMIT 1
            """, (token,))
            return cursor.fetchone()
    finally:
        conn.close()


def confirm_login_token(token: str, guest_id: int, club_id: int, telegram_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_guest_login_tokens_club_column(cursor)
            cursor.execute("""
                UPDATE guest_login_tokens
                SET guest_id = %s,
                    club_id = %s,
                    telegram_id = %s,
                    is_confirmed = 1
                WHERE token = %s
            """, (guest_id, club_id, telegram_id, token))
        conn.commit()
    finally:
        conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    args = context.args

    if args and args[0].startswith("login_"):
        token = args[0].replace("login_", "", 1).strip()

        if not token:
            await message.reply_text("Некорректная ссылка для входа.")
            return

        token_row = get_login_token_row(token)
        if not token_row:
            await message.reply_text("Токен входа не найден.")
            return

        expires_at = token_row.get("expires_at")
        if expires_at and expires_at < datetime.utcnow():
            await message.reply_text("Время входа истекло. Вернитесь на сайт и откройте страницу входа заново.")
            return

        context.user_data["guest_login_token"] = token

        keyboard = [
            [KeyboardButton("Отправить номер телефона", request_contact=True)]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.reply_text(
            "Для входа отправьте свой номер телефона кнопкой ниже.",
            reply_markup=reply_markup
        )
        return

    keyboard = [
        [KeyboardButton("Отправить номер телефона", request_contact=True)]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.reply_text(
        "Для входа откройте страницу входа на сайте и перейдите по QR-коду.",
        reply_markup=reply_markup
    )


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.contact:
        return

    contact = message.contact
    user = update.effective_user

    if not user:
        await message.reply_text("Не удалось определить пользователя.")
        return

    token = context.user_data.get("guest_login_token")
    if not token:
        await message.reply_text(
            "Сначала откройте страницу входа на сайте и перейдите в бота по QR-коду.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    token_row = get_login_token_row(token)
    if not token_row:
        await message.reply_text(
            "Токен входа не найден.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    expires_at = token_row.get("expires_at")
    if expires_at and expires_at < datetime.utcnow():
        await message.reply_text(
            "Время входа истекло. Откройте страницу входа заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if contact.user_id and contact.user_id != user.id:
        await message.reply_text(
            "Пожалуйста, отправьте именно свой номер телефона.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    token_club_id = token_row.get("club_id")
    if not token_club_id:
        await message.reply_text(
            "Ссылка входа устарела. Откройте страницу входа клуба заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    guest, matches_count = find_guest_by_phone(contact.phone_number, int(token_club_id))

    if matches_count > 1:
        await message.reply_text(
            "Найдено несколько гостей с таким номером. Обратитесь к администратору клуба.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if not guest:
        await message.reply_text(
            "Не можем найти Ваш номер! Если вы еще не зарегистрированы в клубе, пройдите регистрацию и возвращайтесь.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    bind_telegram_to_guest(
        guest_id=guest["guest_id"],
        club_id=guest["club_id"],
        telegram_id=user.id
    )

    confirm_login_token(
        token=token,
        guest_id=guest["guest_id"],
        club_id=guest["club_id"],
        telegram_id=user.id
    )

    guest_name = guest.get("fio") or f"ID {guest['guest_id']}"

    welcome_token_added = False
    try:
        welcome_token_added = award_first_authorization_token(
            guest_id=int(guest["guest_id"]),
            club_id=int(guest["club_id"]),
            amount=1,
        )
    except Exception:
        logging.exception(
            "Failed to award first authorization token: guest_id=%s club_id=%s",
            guest.get("guest_id"),
            guest.get("club_id"),
        )

    if welcome_token_added:
        login_text = (
            f"Готово! Вход подтвержден.\n"
            f"Гость: {guest_name}\n\n"
            "Круто! Вот твой первый жетон 🪙\n"
            "Вернись на страницу авторизации — вход выполнится автоматически. "
            "Открой личный кабинет и испытай удачу!"
        )
    else:
        login_text = (
            f"Готово! Вход подтвержден.\n"
            f"Гость: {guest_name}\n"
            "Вернитесь на страницу сайта — вход выполнится автоматически."
        )

    await message.reply_text(
        login_text,
        reply_markup=ReplyKeyboardRemove()
    )



async def first_visit_survey_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    match = re.match(r"^first_visit_survey_start:(\d+)$", data)
    if not match:
        await query.answer("Некорректная кнопка", show_alert=True)
        return

    survey_id = int(match.group(1))
    user = update.effective_user
    if not user:
        await query.answer("Не удалось определить пользователя", show_alert=True)
        return

    conn = get_db_connection()
    try:
        survey = get_survey_for_callback(conn, survey_id, telegram_id=user.id)
        if not survey:
            await query.answer("Этот опрос не найден для вашего Telegram", show_alert=True)
            return
        if survey.get("status") == "completed":
            await query.answer("Опрос уже пройден", show_alert=True)
            return
        mark_survey_started(conn, survey_id)
    finally:
        conn.close()

    keyboard = [[
        InlineKeyboardButton("1 😡", callback_data=f"first_visit_survey_rate:{survey_id}:1"),
        InlineKeyboardButton("2 😕", callback_data=f"first_visit_survey_rate:{survey_id}:2"),
        InlineKeyboardButton("3 😐", callback_data=f"first_visit_survey_rate:{survey_id}:3"),
        InlineKeyboardButton("4 🙂", callback_data=f"first_visit_survey_rate:{survey_id}:4"),
        InlineKeyboardButton("5 😍", callback_data=f"first_visit_survey_rate:{survey_id}:5"),
    ]]

    await query.edit_message_text(
        "Оцените компьютерный клуб после первого визита 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    await query.answer()


async def first_visit_survey_rate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    match = re.match(r"^first_visit_survey_rate:(\d+):(\d+)$", data)
    if not match:
        await query.answer("Некорректная оценка", show_alert=True)
        return

    survey_id = int(match.group(1))
    rating = int(match.group(2))
    user = update.effective_user
    if not user:
        await query.answer("Не удалось определить пользователя", show_alert=True)
        return

    if rating < 1 or rating > 5:
        await query.answer("Оценка должна быть от 1 до 5", show_alert=True)
        return

    conn = get_db_connection()
    try:
        survey = get_survey_for_callback(conn, survey_id, telegram_id=user.id)
        if not survey:
            await query.answer("Этот опрос не найден для вашего Telegram", show_alert=True)
            return
        if survey.get("status") == "completed":
            await query.answer("Опрос уже пройден", show_alert=True)
            return
        save_survey_rating(conn, survey_id, rating)
    finally:
        conn.close()

    context.user_data["first_visit_survey_id"] = survey_id
    context.user_data["first_visit_survey_rating"] = rating
    context.user_data["awaiting_first_visit_feedback"] = True

    if rating >= 4:
        question = (
            "Спасибо за оценку! \n\n"
            "Что можно было бы добавить или улучшить в клубе? Напиши одним сообщением.\n\n"
            "Если всё понравилось, после опроса можно оставить отзыв на Яндекс Картах — "
            "за отзыв можно получить дополнительные бонусы по акции ⭐"
        )
    else:
        question = "Спасибо за честную оценку. Расскажи, пожалуйста, что не понравилось? Напиши одним сообщением."

    await query.edit_message_text(question)
    await query.answer()


async def handle_first_visit_survey_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.message
    user = update.effective_user
    if not message or not user or not message.text:
        return False

    survey_id = context.user_data.get("first_visit_survey_id")
    conn = get_db_connection()
    try:
        survey = None
        if survey_id:
            survey = get_survey_for_callback(conn, int(survey_id), telegram_id=user.id)
        if not survey:
            survey = find_waiting_survey(conn, user.id)
            if survey:
                survey_id = int(survey["id"])

        if not survey or survey.get("status") != "awaiting_feedback":
            return False

        result = complete_survey_and_award(conn, int(survey_id), message.text.strip())
        if not result.get("ok"):
            await message.reply_text(result.get("message") or "Не удалось сохранить ответ.")
            return True

        social_message = build_social_links_message(
            conn,
            int(survey["club_id"]),
            rating=int(survey.get("rating") or 0),
        )
    finally:
        conn.close()

    context.user_data.pop("first_visit_survey_id", None)
    context.user_data.pop("first_visit_survey_rating", None)
    context.user_data.pop("awaiting_first_visit_feedback", None)

    await message.reply_text(
        social_message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return True


async def prize_claim_issued_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def done_prize_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    logging.info(
        "DONE COMMAND RECEIVED: chat_id=%s user_id=%s text=%s args=%s",
        update.effective_chat.id if update.effective_chat else None,
        update.effective_user.id if update.effective_user else None,
        message.text if message else None,
        context.args,
    )

    raw_claim_id = None

    if context.args:
        raw_claim_id = context.args[0].strip()
    else:
        # Fallback for group chats where CommandHandler may not parse args reliably,
        # and for commands like /done@BotUsername 123 caught by Regex MessageHandler.
        match = re.search(r"^/done(?:@\w+)?\s+(\d+)\s*$", message.text or "", flags=re.IGNORECASE)
        if match:
            raw_claim_id = match.group(1)

    if not raw_claim_id:
        await message.reply_text("Укажи ID заявки: /done 123")
        return

    try:
        claim_id = int(raw_claim_id)
    except ValueError:
        await message.reply_text("ID заявки должен быть числом. Пример: /done 123")
        return

    user = update.effective_user
    chat = update.effective_chat
    username = None
    if user:
        username = f"@{user.username}" if user.username else user.full_name

    try:
        result = mark_prize_claim_issued_by_telegram(
            claim_id=claim_id,
            chat_id=chat.id if chat else None,
            telegram_id=user.id if user else None,
            username=username,
        )
    except Exception as e:
        logging.exception("Ошибка при выдаче приза #%s", claim_id)
        await message.reply_text(f"Не удалось отметить приз #{claim_id} как выданный: {e}")
        return

    if not result.get("ok"):
        await message.reply_text(result.get("message") or f"Не удалось закрыть заявку #{claim_id}.")
        return

    claim = result.get("claim") or {}
    prize_name = claim.get("prize_name") or "Приз"
    guest_name = claim.get("guest_name") or f"Guest ID {claim.get('guest_id')}"
    prefix = "ℹ️" if result.get("already_done") else "✅"
    await message.reply_text(
        f"{prefix} Приз #{claim_id} отмечен как выдан.\n"
        f"Гость: {guest_name}\n"
        f"Приз: {prize_name}"
    )


async def route_done_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hard fallback for group chats where /done is delivered as plain text."""
    message = update.message
    text = (message.text or "").strip() if message else ""

    logging.info(
        "TEXT UPDATE RECEIVED: chat_id=%s user_id=%s text=%s",
        update.effective_chat.id if update.effective_chat else None,
        update.effective_user.id if update.effective_user else None,
        text,
    )

    if re.match(r"^/done(?:@\w+)?\s+\d+\s*$", text, flags=re.IGNORECASE):
        await done_prize_claim(update, context)
        raise ApplicationHandlerStop


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_first_visit_survey_feedback(update, context):
        return

    message = update.message
    if not message:
        return

    keyboard = [
        [KeyboardButton("Отправить номер телефона", request_contact=True)]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.reply_text(
        "Нажмите кнопку ниже и отправьте номер телефона.",
        reply_markup=reply_markup
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Ошибка в боте:", exc_info=context.error)


def main():
    builder = ApplicationBuilder().token(BOT_TOKEN)

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

    app.add_handler(CallbackQueryHandler(first_visit_survey_start_callback, pattern=r"^first_visit_survey_start:\d+$"), group=-3)
    app.add_handler(CallbackQueryHandler(first_visit_survey_rate_callback, pattern=r"^first_visit_survey_rate:\d+:\d+$"), group=-3)
    app.add_handler(CallbackQueryHandler(prize_claim_issued_callback, pattern=r"^prize_claim_issued:\d+$"), group=-2)

    # Hard fallback: logs all incoming text and handles /done before other handlers.
    # This helps in groups/supergroups where Telegram may deliver /done as plain text.
    app.add_handler(MessageHandler(filters.TEXT, route_done_text), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done_prize_claim))

    # Extra fallback for group chats and explicit bot mentions:
    # /done 123 and /done@BotUsername 123
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^/done(@\w+)?\s+\d+\s*$"),
            done_prize_claim,
        )
    )

    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
