import asyncio
from collections import deque
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import support_tickets as service
from bot import support_tickets as bot_tickets


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = deque(rows)
        self.executed = []
        self.lastrowid = 214

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.rows.popleft() if self.rows else None

    def fetchall(self):
        return self.rows.popleft() if self.rows else []


class FakeConnection:
    def __init__(self, rows=()):
        self.cursor_obj = FakeCursor(rows)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def ticket(**overrides):
    value = {
        "id": 214,
        "club_id": 1,
        "club_name": "Клуб <Тест>",
        "club_timezone": "Europe/Moscow",
        "source_chat_id": "-1001",
        "source_message_id": 77,
        "author_telegram_id": 42,
        "author_username": "@user",
        "author_name": "Иван <Иванов>",
        "message_text": "Не выдаётся <приз>",
        "status": service.STATUS_WAITING,
        "assigned_to_name": None,
        "assigned_to_username": None,
        "technical_chat_id": "-5206784490",
        "created_at": datetime(2026, 9, 14, 9, 30),
    }
    value.update(overrides)
    return value


def test_technical_message_escapes_user_content_and_shows_context():
    text = service.format_technical_ticket(ticket())

    assert "Заявка №214" in text
    assert "Клуб &lt;Тест&gt;" in text
    assert "Иван &lt;Иванов&gt;" in text
    assert "Не выдаётся &lt;приз&gt;" in text
    assert "14.09.2026 12:30" in text


def test_ticket_keyboard_follows_status_machine():
    waiting = bot_tickets.keyboard_for_ticket(ticket())
    active = bot_tickets.keyboard_for_ticket(ticket(status=service.STATUS_IN_PROGRESS))
    paused = bot_tickets.keyboard_for_ticket(ticket(status=service.STATUS_PAUSED))
    completed = bot_tickets.keyboard_for_ticket(ticket(status=service.STATUS_COMPLETED))

    assert waiting.inline_keyboard[0][0].callback_data == "support_ticket:214:take"
    assert [button.text for button in active.inline_keyboard[0]] == ["Пауза", "Выполнено"]
    assert [button.text for button in paused.inline_keyboard[0]] == ["Продолжить", "Выполнено"]
    assert completed is None


def test_transition_is_atomic_and_records_actor(monkeypatch):
    before = ticket()
    after = ticket(
        status=service.STATUS_IN_PROGRESS,
        assigned_to_telegram_id=99,
        assigned_to_username="@operator",
        assigned_to_name="Оператор",
    )
    conn = FakeConnection([before, after])
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)

    result = service.transition_support_ticket(
        ticket_id=214,
        action="take",
        technical_chat_id=-5206784490,
        actor_telegram_id=99,
        actor_username="@operator",
        actor_name="Оператор",
    )

    assert result["ok"] is True
    assert result["ticket"]["status"] == service.STATUS_IN_PROGRESS
    assert conn.committed is True
    update = next((params for query, params in conn.cursor_obj.executed if "UPDATE support_tickets" in query), None)
    event = next(
        (params for query, params in conn.cursor_obj.executed if "INSERT INTO support_ticket_events" in query),
        None,
    )
    assert update[0:4] == (service.STATUS_IN_PROGRESS, 99, "@operator", "Оператор")
    assert event[0:6] == (214, "take", service.STATUS_WAITING, service.STATUS_IN_PROGRESS, 99, "@operator")


def test_stale_button_does_not_change_completed_ticket(monkeypatch):
    conn = FakeConnection([ticket(status=service.STATUS_COMPLETED)])
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)

    result = service.transition_support_ticket(
        ticket_id=214,
        action="take",
        technical_chat_id=-5206784490,
        actor_telegram_id=99,
        actor_username=None,
        actor_name="Оператор",
    )

    assert result["ok"] is False
    assert result["changed"] is False
    assert conn.rolled_back is True
    assert not any("UPDATE support_tickets" in query for query, _params in conn.cursor_obj.executed)


def test_ticket_command_creates_and_delivers_ticket(monkeypatch):
    message = SimpleNamespace(
        text="/ticket не проходит выдача приза",
        caption=None,
        reply_to_message=None,
        message_id=77,
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Админы клуба"),
        effective_user=SimpleNamespace(id=42, username="user", full_name="Иван Иванов"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=501))))
    recorded = []
    monkeypatch.setattr(bot_tickets, "TECH_SUPPORT_CHAT_ID", "-5206784490")
    monkeypatch.setattr(
        bot_tickets,
        "get_club_for_ticket_chat",
        lambda _chat_id: {"club_id": 1, "name": "Клуб", "timezone": "Europe/Moscow"},
    )
    monkeypatch.setattr(bot_tickets, "create_support_ticket", lambda **_kwargs: ticket())
    monkeypatch.setattr(
        bot_tickets,
        "record_technical_delivery",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    asyncio.run(bot_tickets.ticket_command(update, context))

    assert context.bot.send_message.await_args.kwargs["chat_id"] == "-5206784490"
    assert recorded[0][1]["technical_message_id"] == 501
    message.reply_text.assert_awaited_once_with("Заявка №214 сформирована.\nСтатус: ожидание оператора.")


def test_ticket_callback_changes_message_and_notifies_club(monkeypatch):
    updated_ticket = ticket(
        status=service.STATUS_IN_PROGRESS,
        assigned_to_name="Оператор",
        assigned_to_username="@operator",
    )
    query = SimpleNamespace(
        data="support_ticket:214:take",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=-5206784490),
        effective_user=SimpleNamespace(id=99, username="operator", full_name="Оператор"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    monkeypatch.setattr(bot_tickets, "TECH_SUPPORT_CHAT_ID", "-5206784490")
    monkeypatch.setattr(
        bot_tickets,
        "transition_support_ticket",
        lambda **_kwargs: {"ok": True, "changed": True, "ticket": updated_ticket},
    )

    asyncio.run(bot_tickets.ticket_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    assert context.bot.send_message.await_args.kwargs["chat_id"] == "-1001"
    assert "взята в работу" in context.bot.send_message.await_args.kwargs["text"]
    query.answer.assert_awaited_once_with("Заявка взята в работу", show_alert=False)
