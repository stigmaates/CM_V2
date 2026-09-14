from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import TECH_SUPPORT_CHAT_ID
from app.services.support_tickets import (
    STATUS_IN_PROGRESS,
    STATUS_PAUSED,
    STATUS_WAITING,
    create_support_ticket,
    format_club_status,
    format_technical_ticket,
    get_club_for_ticket_chat,
    record_club_status_message,
    record_technical_delivery,
    transition_support_ticket,
)

TICKET_CALLBACK_PATTERN = r"^support_ticket:\d+:(take|pause|resume|complete)$"


def _ticket_text(update: Update) -> str:
    message = update.effective_message
    raw_text = (message.text or message.caption or "") if message else ""
    match = re.match(r"^/ticket(?:@\w+)?(?:\s+([\s\S]+))?$", raw_text.strip(), flags=re.IGNORECASE)
    text = (match.group(1) if match else "") or ""
    if text.strip():
        return text.strip()
    replied = message.reply_to_message if message else None
    return ((replied.text or replied.caption or "") if replied else "").strip()


def ticket_keyboard(status: str) -> InlineKeyboardMarkup | None:
    if status == STATUS_WAITING:
        rows = [[InlineKeyboardButton("Взять в работу", callback_data="support_ticket:{id}:take")]]
    elif status == STATUS_IN_PROGRESS:
        rows = [[
            InlineKeyboardButton("Пауза", callback_data="support_ticket:{id}:pause"),
            InlineKeyboardButton("Выполнено", callback_data="support_ticket:{id}:complete"),
        ]]
    elif status == STATUS_PAUSED:
        rows = [[
            InlineKeyboardButton("Продолжить", callback_data="support_ticket:{id}:resume"),
            InlineKeyboardButton("Выполнено", callback_data="support_ticket:{id}:complete"),
        ]]
    else:
        return None
    return InlineKeyboardMarkup(rows)


def keyboard_for_ticket(ticket: dict) -> InlineKeyboardMarkup | None:
    markup = ticket_keyboard(str(ticket.get("status") or ""))
    if not markup:
        return None
    ticket_id = int(ticket["id"])
    rows = []
    for row in markup.inline_keyboard:
        rows.append([
            InlineKeyboardButton(button.text, callback_data=(button.callback_data or "").format(id=ticket_id))
            for button in row
        ])
    return InlineKeyboardMarkup(rows)


def _message_link(message) -> str | None:
    try:
        link = message.link
    except Exception:
        return None
    return str(link).strip() or None


def _record_club_message(ticket_id: int, message_id: int | None) -> None:
    if message_id is None:
        return
    try:
        record_club_status_message(ticket_id, message_id)
    except Exception:
        logging.exception("Failed to record club status message for support ticket #%s", ticket_id)


async def _send_new_club_status(context, ticket: dict, text: str):
    try:
        sent = await context.bot.send_message(
            chat_id=ticket["source_chat_id"],
            text=text,
            reply_to_message_id=ticket.get("source_message_id"),
        )
    except Exception:
        logging.exception("Failed to reply to source message for support ticket #%s", ticket["id"])
        sent = await context.bot.send_message(chat_id=ticket["source_chat_id"], text=text)
    _record_club_message(int(ticket["id"]), getattr(sent, "message_id", None))


async def _update_club_status(context, ticket: dict, action: str) -> None:
    text = format_club_status(ticket, action)
    message_id = ticket.get("club_status_message_id")
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=ticket["source_chat_id"],
                message_id=message_id,
                text=text,
            )
            return
        except Exception:
            logging.exception("Failed to edit club status message for support ticket #%s", ticket["id"])
    await _send_new_club_status(context, ticket, text)


async def ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat:
        return
    if chat.type not in {"group", "supergroup"}:
        await message.reply_text("Создайте заявку командой /ticket в беседе своего клуба.")
        return
    if not (TECH_SUPPORT_CHAT_ID or "").strip():
        logging.error("TECH_SUPPORT_CHAT_ID is empty; support ticket command is unavailable")
        await message.reply_text("Сервис заявок пока не настроен. Сообщите об этом сотруднику поддержки.")
        return

    try:
        club = get_club_for_ticket_chat(chat.id)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    if not club:
        await message.reply_text("Эта беседа не привязана к клубу. Заявка не создана.")
        return

    text = _ticket_text(update)
    if not text:
        await message.reply_text("Напишите обращение после команды.\nНапример: /ticket не проходит выдача приза")
        return

    username = f"@{user.username}" if user and user.username else None
    try:
        ticket = create_support_ticket(
            club_id=int(club["club_id"]),
            source_chat_id=chat.id,
            source_chat_title=getattr(chat, "title", None),
            source_message_id=message.message_id,
            source_message_link=_message_link(message),
            author_telegram_id=user.id if user else None,
            author_username=username,
            author_name=user.full_name if user else None,
            message_text=text,
        )
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    except Exception:
        logging.exception("Failed to create support ticket")
        await message.reply_text("Не удалось создать заявку. Попробуйте ещё раз через минуту.")
        return

    try:
        technical_message = await context.bot.send_message(
            chat_id=TECH_SUPPORT_CHAT_ID,
            text=format_technical_ticket(ticket),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard_for_ticket(ticket),
        )
    except Exception as exc:
        logging.exception("Failed to deliver support ticket #%s to technical chat", ticket["id"])
        try:
            record_technical_delivery(
                int(ticket["id"]),
                technical_chat_id=TECH_SUPPORT_CHAT_ID,
                error=str(exc),
            )
        except Exception:
            logging.exception("Failed to record delivery error for support ticket #%s", ticket["id"])
        await message.reply_text(
            f"Заявка №{int(ticket['id'])} сохранена, но техническая беседа временно недоступна. "
            "Сообщите номер заявки сотруднику поддержки."
        )
        return

    try:
        record_technical_delivery(
            int(ticket["id"]),
            technical_chat_id=TECH_SUPPORT_CHAT_ID,
            technical_message_id=technical_message.message_id,
        )
    except Exception:
        # The callback still contains the ticket ID, so the operator can process
        # it even if recording Telegram's message ID failed.
        logging.exception("Failed to record technical message for support ticket #%s", ticket["id"])

    club_message = await message.reply_text(format_club_status(ticket, "create"))
    _record_club_message(int(ticket["id"]), getattr(club_message, "message_id", None))


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    title = getattr(chat, "title", None) or "личный чат"
    await message.reply_text(f"ID беседы «{title}»: {chat.id}")


async def ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    if not query or not chat:
        return

    match = re.match(TICKET_CALLBACK_PATTERN, query.data or "")
    if not match:
        await query.answer("Некорректная кнопка", show_alert=True)
        return
    if str(chat.id) != str(TECH_SUPPORT_CHAT_ID):
        await query.answer("Кнопка доступна только в технической беседе", show_alert=True)
        return

    ticket_id = int((query.data or "").split(":")[1])
    action = match.group(1)
    username = f"@{user.username}" if user and user.username else None
    try:
        result = transition_support_ticket(
            ticket_id=ticket_id,
            action=action,
            technical_chat_id=chat.id,
            actor_telegram_id=user.id if user else None,
            actor_username=username,
            actor_name=user.full_name if user else None,
        )
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return
    except Exception:
        logging.exception("Failed to change support ticket #%s", ticket_id)
        await query.answer("Не удалось изменить статус заявки", show_alert=True)
        return

    ticket = result.get("ticket") or {}
    if not result.get("changed"):
        await query.answer(result.get("message") or "Статус заявки уже изменён", show_alert=False)
    else:
        action_answers = {
            "take": "Заявка взята в работу",
            "pause": "Заявка поставлена на паузу",
            "resume": "Работа по заявке продолжена",
            "complete": "Заявка выполнена",
        }
        await query.answer(action_answers[action], show_alert=False)

    try:
        await query.edit_message_text(
            text=format_technical_ticket(ticket),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard_for_ticket(ticket),
        )
    except Exception:
        logging.exception("Failed to refresh technical message for support ticket #%s", ticket_id)

    if not result.get("changed"):
        return

    try:
        await _update_club_status(context, ticket, action)
    except Exception:
        logging.exception("Failed to notify club chat about support ticket #%s", ticket_id)
