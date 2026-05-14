import logging
import re
from datetime import datetime
from telegram.request import HTTPXRequest

import pymysql
from pymysql.cursors import DictCursor

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import BOT_TOKEN, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, TG_PROXY_URL


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


def normalize_phone(phone: str):
    if not phone:
        return None

    digits = re.sub(r"\D", "", phone)

    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    if len(digits) == 10:
        digits = "7" + digits

    return digits


def find_guest_by_phone(phone: str):
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None, 0

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT guest_id, club_id, fio, phone, telegram_id
                FROM guests
            """)
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


def bind_telegram_to_guest(guest_id: int, telegram_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE guests
                SET telegram_id = %s
                WHERE guest_id = %s
            """, (telegram_id, guest_id))
        conn.commit()
    finally:
        conn.close()


def get_login_token_row(token: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT token, guest_id, telegram_id, is_confirmed, created_at, expires_at
                FROM guest_login_tokens
                WHERE token = %s
                LIMIT 1
            """, (token,))
            return cursor.fetchone()
    finally:
        conn.close()


def confirm_login_token(token: str, guest_id: int, telegram_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE guest_login_tokens
                SET guest_id = %s,
                    telegram_id = %s,
                    is_confirmed = 1
                WHERE token = %s
            """, (guest_id, telegram_id, token))
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

    guest, matches_count = find_guest_by_phone(contact.phone_number)

    if matches_count > 1:
        await message.reply_text(
            "Найдено несколько гостей с таким номером. Обратитесь к администратору клуба.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if not guest:
        await message.reply_text(
            "Гость с таким номером не найден. Проверьте номер в системе клуба.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    bind_telegram_to_guest(
        guest_id=guest["guest_id"],
        telegram_id=user.id
    )

    confirm_login_token(
        token=token,
        guest_id=guest["guest_id"],
        telegram_id=user.id
    )

    guest_name = guest.get("fio") or f"ID {guest['guest_id']}"

    await message.reply_text(
        f"Готово! Вход подтвержден.\nГость: {guest_name}\nВернитесь на страницу сайта — вход выполнится автоматически.",
        reply_markup=ReplyKeyboardRemove()
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    app.run_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()