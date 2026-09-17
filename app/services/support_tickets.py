from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

from app.core import get_db_connection
from app.services.timezones import DEFAULT_CLUB_TIMEZONE, utc_datetime_to_club_local

STATUS_WAITING = "waiting"
STATUS_IN_PROGRESS = "in_progress"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"

STATUS_LABELS = {
    STATUS_WAITING: "ожидание оператора",
    STATUS_IN_PROGRESS: "в работе",
    STATUS_PAUSED: "пауза",
    STATUS_COMPLETED: "выполнено",
}

ACTION_TRANSITIONS = {
    "take": ({STATUS_WAITING}, STATUS_IN_PROGRESS),
    "pause": ({STATUS_IN_PROGRESS}, STATUS_PAUSED),
    "resume": ({STATUS_PAUSED}, STATUS_IN_PROGRESS),
    "complete": ({STATUS_IN_PROGRESS, STATUS_PAUSED}, STATUS_COMPLETED),
}

MAX_TICKET_TEXT_LENGTH = 3000


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_club_for_ticket_chat(chat_id: int | str) -> dict[str, Any] | None:
    """Resolve a club only from its configured admin chat."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT club_id, name, COALESCE(timezone, %s) AS timezone
                FROM clubs
                WHERE cm_bonus_admin_chat_id = %s
                ORDER BY club_id
                LIMIT 2
                """,
                (DEFAULT_CLUB_TIMEZONE, str(chat_id)),
            )
            rows = cursor.fetchall()
        if len(rows) > 1:
            raise ValueError("Эта Telegram-беседа привязана сразу к нескольким клубам")
        return rows[0] if rows else None
    finally:
        conn.close()


def create_support_ticket(
    *,
    club_id: int,
    source_chat_id: int | str,
    source_chat_title: str | None,
    source_message_id: int | None,
    author_telegram_id: int | None,
    author_username: str | None,
    author_name: str | None,
    message_text: str,
) -> dict[str, Any]:
    text = (message_text or "").strip()
    if not text:
        raise ValueError("Напишите обращение после команды /ticket")
    if len(text) > MAX_TICKET_TEXT_LENGTH:
        raise ValueError(f"Обращение длиннее {MAX_TICKET_TEXT_LENGTH} символов")

    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO support_tickets (
                    club_id, source_chat_id, source_chat_title, source_message_id,
                    author_telegram_id, author_username, author_name, message_text,
                    status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(club_id),
                    str(source_chat_id),
                    (source_chat_title or "").strip()[:255] or None,
                    source_message_id,
                    author_telegram_id,
                    (author_username or "").strip()[:255] or None,
                    (author_name or "").strip()[:255] or None,
                    text,
                    STATUS_WAITING,
                    now,
                    now,
                ),
            )
            ticket_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO support_ticket_events (
                    ticket_id, action, old_status, new_status,
                    actor_telegram_id, actor_username, actor_name, created_at
                )
                VALUES (%s, 'create', NULL, %s, %s, %s, %s, %s)
                """,
                (
                    ticket_id,
                    STATUS_WAITING,
                    author_telegram_id,
                    (author_username or "").strip()[:255] or None,
                    (author_name or "").strip()[:255] or None,
                    now,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return get_support_ticket(ticket_id)


def get_support_ticket(ticket_id: int) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.*, c.name AS club_name, COALESCE(c.timezone, %s) AS club_timezone
                FROM support_tickets t
                JOIN clubs c ON c.club_id = t.club_id
                WHERE t.id = %s
                LIMIT 1
                """,
                (DEFAULT_CLUB_TIMEZONE, int(ticket_id)),
            )
            row = cursor.fetchone()
        if not row:
            raise ValueError(f"Заявка №{ticket_id} не найдена")
        return row
    finally:
        conn.close()


def record_technical_delivery(
    ticket_id: int,
    *,
    technical_chat_id: int | str | None,
    technical_message_id: int | None = None,
    error: str | None = None,
) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE support_tickets
                SET technical_chat_id = %s,
                    technical_message_id = %s,
                    delivery_error = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    str(technical_chat_id) if technical_chat_id is not None else None,
                    technical_message_id,
                    (error or "")[:2000] or None,
                    _utcnow(),
                    int(ticket_id),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def transition_support_ticket(
    *,
    ticket_id: int,
    action: str,
    technical_chat_id: int | str,
    actor_telegram_id: int | None,
    actor_username: str | None,
    actor_name: str | None,
) -> dict[str, Any]:
    transition = ACTION_TRANSITIONS.get(action)
    if not transition:
        raise ValueError("Неизвестное действие с заявкой")
    allowed_statuses, new_status = transition
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.*, c.name AS club_name, COALESCE(c.timezone, %s) AS club_timezone
                FROM support_tickets t
                JOIN clubs c ON c.club_id = t.club_id
                WHERE t.id = %s
                FOR UPDATE
                """,
                (DEFAULT_CLUB_TIMEZONE, int(ticket_id)),
            )
            ticket = cursor.fetchone()
            if not ticket:
                raise ValueError(f"Заявка №{ticket_id} не найдена")

            recorded_chat = str(ticket.get("technical_chat_id") or "").strip()
            callback_chat = str(technical_chat_id)
            if recorded_chat and recorded_chat != callback_chat:
                raise ValueError("Эта кнопка доступна только в технической беседе")

            old_status = ticket.get("status")
            if old_status not in allowed_statuses:
                conn.rollback()
                return {
                    "ok": False,
                    "changed": False,
                    "message": f"Заявка уже имеет статус «{STATUS_LABELS.get(old_status, old_status)}»",
                    "ticket": ticket,
                }

            update_assignee = action in {"take", "resume"}
            assignee_params: tuple[Any, ...] = ()
            if update_assignee:
                assignee_params = (
                    actor_telegram_id,
                    (actor_username or "").strip()[:255] or None,
                    (actor_name or "").strip()[:255] or None,
                )

            assignments = ["status = %s"]
            update_params: list[Any] = [new_status]
            if update_assignee:
                assignments.extend(
                    [
                        "assigned_to_telegram_id = %s",
                        "assigned_to_username = %s",
                        "assigned_to_name = %s",
                    ]
                )
                update_params.extend(assignee_params)
            if action == "take":
                assignments.append("taken_at = COALESCE(taken_at, %s)")
                update_params.append(now)
            elif action == "pause":
                assignments.append("paused_at = %s")
                update_params.append(now)
            elif action == "complete":
                assignments.append("completed_at = %s")
                update_params.append(now)
            assignments.append("updated_at = %s")
            update_params.extend((now, int(ticket_id)))
            cursor.execute(
                """
                UPDATE support_tickets
                SET """
                + ", ".join(assignments)
                + """
                WHERE id = %s
                """,
                tuple(update_params),
            )
            cursor.execute(
                """
                INSERT INTO support_ticket_events (
                    ticket_id, action, old_status, new_status,
                    actor_telegram_id, actor_username, actor_name, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(ticket_id),
                    action,
                    old_status,
                    new_status,
                    actor_telegram_id,
                    (actor_username or "").strip()[:255] or None,
                    (actor_name or "").strip()[:255] or None,
                    now,
                ),
            )
            cursor.execute(
                """
                SELECT t.*, c.name AS club_name, COALESCE(c.timezone, %s) AS club_timezone
                FROM support_tickets t
                JOIN clubs c ON c.club_id = t.club_id
                WHERE t.id = %s
                LIMIT 1
                """,
                (DEFAULT_CLUB_TIMEZONE, int(ticket_id)),
            )
            updated = cursor.fetchone()
        conn.commit()
        return {"ok": True, "changed": True, "ticket": updated}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def format_technical_ticket(ticket: dict[str, Any]) -> str:
    status = STATUS_LABELS.get(ticket.get("status"), str(ticket.get("status") or "—"))
    created_at = ticket.get("created_at")
    local_created = utc_datetime_to_club_local(created_at, ticket.get("club_timezone")) if created_at else None
    created_text = local_created.strftime("%d.%m.%Y %H:%M") if local_created else "—"
    timezone_name = ticket.get("club_timezone") or DEFAULT_CLUB_TIMEZONE

    author = escape(str(ticket.get("author_name") or "Неизвестный пользователь"))
    username = str(ticket.get("author_username") or "").strip()
    if username:
        author += f" ({escape(username if username.startswith('@') else '@' + username)})"
    author_id = ticket.get("author_telegram_id")
    if author_id:
        author += f", ID {int(author_id)}"

    assignee = ""
    if ticket.get("assigned_to_name") or ticket.get("assigned_to_username"):
        assigned_name = escape(str(ticket.get("assigned_to_name") or ticket.get("assigned_to_username")))
        assigned_username = str(ticket.get("assigned_to_username") or "").strip()
        if assigned_username and assigned_username not in assigned_name:
            displayed_username = assigned_username if assigned_username.startswith("@") else "@" + assigned_username
            assigned_name += f" ({escape(displayed_username)})"
        assignee = f"\n<b>Ответственный:</b> {assigned_name}"

    return (
        f"<b>🎫 Заявка №{int(ticket['id'])}</b>\n"
        f"<b>Статус:</b> {escape(status)}\n"
        f"<b>Время:</b> {created_text} ({escape(timezone_name)})\n"
        f"<b>Клуб:</b> {escape(str(ticket.get('club_name') or ticket.get('club_id') or '—'))}\n"
        f"<b>Отправитель:</b> {author}{assignee}\n\n"
        f"<b>Обращение:</b>\n{escape(str(ticket.get('message_text') or ''))}"
    )


def format_club_status(ticket: dict[str, Any], action: str = "create") -> str:
    ticket_id = int(ticket["id"])
    messages = {
        "create": f"Заявка №{ticket_id} сформирована.\nСтатус: ожидание оператора.",
        "take": f"Заявка №{ticket_id} взята в работу.\nСотрудники уже занимаются вашим вопросом.",
        "pause": f"Заявка №{ticket_id} поставлена на паузу.\nРабота по вопросу временно приостановлена.",
        "resume": f"Заявка №{ticket_id} снова в работе.\nСотрудники продолжают заниматься вашим вопросом.",
        "complete": f"Заявка №{ticket_id} выполнена.\nЕсли вопрос остался, создайте новую заявку командой /ticket.",
    }
    return messages[action]
