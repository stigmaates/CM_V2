import asyncio
from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import telegram_links as service
from bot import main as guest_bot
from bot import telegram_link_flow as flow


class Cursor:
    def __init__(self, rows):
        self.rows = deque(rows)
        self.executed = []
        self.lastrowid = 42

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.rows.popleft()


class Connection:
    def __init__(self, rows):
        self.cur = Cursor(rows)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def begin(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def request_row(**changes):
    return dict(
        id=42,
        club_id=2,
        guest_id=7,
        telegram_id=100,
        lg_phone="9270086145",
        admin_chat_id="-200",
        status="pending",
        expired=False,
        **changes,
    )


def review_db(monkeypatch, row=None, guest=None, other=None):
    conn = Connection(
        [
            {"club_id": 2},
            {"club_id": 2},
            row or request_row(),
            {"cm_bonus_admin_chat_id": "-200"},
            guest or {"guest_id": 7, "telegram_id": None, "phone": "9270086145"},
            other,
        ]
    )
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    return conn


def test_approval_binds_and_records_reviewer_atomically(monkeypatch):
    conn = review_db(monkeypatch)
    row = service.review_link_request(42, -200, 55, True)
    assert row["telegram_id"] == 100
    assert conn.committed and not conn.rolled_back
    writes = [(q, p) for q, p in conn.cur.executed if q.startswith("UPDATE")]
    assert writes[0][1] == (100, 2, 7)
    assert writes[1][1] == ("approved", 55, 42)


def test_rejection_does_not_change_guest(monkeypatch):
    conn = review_db(monkeypatch)
    service.review_link_request(42, -200, 55, False)
    assert conn.committed
    assert not any(q.startswith("UPDATE guests") for q, _ in conn.cur.executed)


@pytest.mark.parametrize(
    "changes,chat_id",
    [
        ({}, -999),
        ({"status": "approved"}, -200),
        ({"expired": True}, -200),
    ],
)
def test_review_rejects_wrong_chat_duplicate_or_expired_request(monkeypatch, changes, chat_id):
    row = request_row()
    row.update(changes)
    conn = review_db(monkeypatch, row=row)
    with pytest.raises(ValueError):
        service.review_link_request(42, chat_id, 55, True)
    assert conn.rolled_back and not conn.committed
    assert not any(q.startswith("UPDATE") for q, _ in conn.cur.executed)


@pytest.mark.parametrize(
    "guest,other",
    [
        ({"guest_id": 7, "telegram_id": 999, "phone": "9270086145"}, None),
        ({"guest_id": 7, "telegram_id": None, "phone": "changed"}, None),
        ({"guest_id": 7, "telegram_id": None, "phone": "9270086145"}, {"guest_id": 8}),
    ],
)
def test_approval_does_not_overwrite_conflicting_link_or_changed_phone(monkeypatch, guest, other):
    conn = review_db(monkeypatch, guest=guest, other=other)
    with pytest.raises(ValueError):
        service.review_link_request(42, -200, 55, True)
    assert conn.rolled_back


def test_request_is_pending_and_does_not_bind_guest(monkeypatch):
    conn = Connection(
        [
            {"club_id": 2},
            {"guest_id": 7, "telegram_id": None, "phone": "9270086145"},
            None,
            None,
            {"n": 0},
        ]
    )
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    assert service.create_link_request(2, 7, 100, "79990000000", "9270086145", -200) == 42
    assert conn.committed
    assert not any(q.startswith("UPDATE guests") for q, _ in conn.cur.executed)


def test_duplicate_pending_request_is_rejected(monkeypatch):
    conn = Connection(
        [
            {"club_id": 2},
            {"guest_id": 7, "telegram_id": None, "phone": "9270086145"},
            None,
            {"id": 42},
        ]
    )
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    with pytest.raises(ValueError, match="ожидает"):
        service.create_link_request(2, 7, 100, "79990000000", "9270086145", -200)
    assert conn.rolled_back


def test_normal_contact_login_cannot_replace_existing_telegram(monkeypatch):
    conn = Connection([{"club_id": 2}, {"guest_id": 7, "telegram_id": 999}])
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    with pytest.raises(ValueError):
        service.bind_verified_contact(7, 2, 100)
    assert conn.rolled_back


def update_and_context(step="choice"):
    message = SimpleNamespace(reply_text=AsyncMock(), text="89270086145")
    query = SimpleNamespace(data="lg_link:abc:help", answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        callback_query=query,
        effective_chat=SimpleNamespace(id=100, type="private"),
        effective_user=SimpleNamespace(id=100),
    )
    context = SimpleNamespace(
        user_data={
            "guest_login_token": "token",
            "phone_link": {
                "token": "token",
                "nonce": "abc",
                "phone": "79990000000",
                "step": step,
            },
        }
    )
    return update, context


def live_token(monkeypatch):
    monkeypatch.setattr(
        guest_bot,
        "get_login_token_row",
        lambda token: {
            "club_id": 2,
            "is_confirmed": 0,
            "expires_at": datetime.utcnow() + timedelta(minutes=5),
        },
    )


@pytest.mark.parametrize("action", ["help", "no"])
def test_guest_help_or_no_ends_flow(monkeypatch, action):
    live_token(monkeypatch)
    update, context = update_and_context()
    update.callback_query.data = f"lg_link:abc:{action}"
    asyncio.run(flow.phone_choice_callback(update, context))
    update.callback_query.edit_message_text.assert_awaited_once_with(service.HELP_MESSAGE)
    assert "phone_link" not in context.user_data


def test_typed_phone_only_shows_confirmation_in_current_club(monkeypatch):
    live_token(monkeypatch)
    update, context = update_and_context("phone")
    monkeypatch.setattr(flow, "is_rate_limited", lambda *args, **kwargs: False)
    seen = []

    def find(phone, club):
        seen.append((phone, club))
        return {"guest_id": 7, "phone": "9270086145", "fio": "Тестовый Гость"}, 1

    monkeypatch.setattr(guest_bot, "find_guest_by_phone", find)
    asyncio.run(flow.handle_lg_phone(update, context))
    assert seen == [("79270086145", 2)]
    assert context.user_data["phone_link"]["step"] == "confirm"
    assert "это ваш аккаунт" in update.message.reply_text.call_args.args[0]


def test_stale_buttons_cannot_submit(monkeypatch):
    live_token(monkeypatch)
    update, context = update_and_context()
    update.callback_query.data = "lg_link:old:yes"
    asyncio.run(flow.phone_choice_callback(update, context))
    assert update.callback_query.answer.call_args.kwargs["show_alert"]
    update.callback_query.edit_message_text.assert_not_called()


def test_expired_token_clears_flow(monkeypatch):
    monkeypatch.setattr(
        guest_bot,
        "get_login_token_row",
        lambda token: {
            "club_id": 2,
            "expires_at": datetime.utcnow() - timedelta(seconds=1),
        },
    )
    update, context = update_and_context("phone")
    asyncio.run(flow.handle_lg_phone(update, context))
    assert "phone_link" not in context.user_data


def test_returning_guest_uses_approved_link_without_phone(monkeypatch):
    live_token(monkeypatch)
    update, context = update_and_context()
    context.args = ["login_token"]
    guest = {"club_id": 2, "guest_id": 7}
    monkeypatch.setattr(guest_bot, "find_linked_guest", lambda club_id, telegram_id: guest)
    complete = AsyncMock()
    monkeypatch.setattr(guest_bot, "complete_guest_login", complete)
    asyncio.run(guest_bot.start(update, context))
    complete.assert_awaited_once_with(update.message, context, guest, 100, "token")
    update.message.reply_text.assert_not_called()


def test_regular_chat_member_cannot_approve(monkeypatch):
    update, context = update_and_context()
    update.callback_query.data = "lg_review:42:yes"
    context.bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))
    asyncio.run(flow.review_callback(update, context))
    assert update.callback_query.answer.call_args.kwargs["show_alert"]


def test_foreign_or_unverified_contact_is_rejected(monkeypatch):
    live_token(monkeypatch)
    update, context = update_and_context()
    update.message.contact = SimpleNamespace(user_id=None, phone_number="79990000000")
    asyncio.run(guest_bot.handle_contact(update, context))
    assert "именно свой номер" in update.message.reply_text.call_args.args[0]


def test_confirm_token_is_scoped_unexpired_and_single_use(monkeypatch):
    conn = Connection([])
    conn.cur.rowcount = 1
    monkeypatch.setattr(guest_bot, "get_db_connection", lambda: conn)
    monkeypatch.setattr(guest_bot, "ensure_guest_login_tokens_club_column", lambda cur: None)
    guest_bot.confirm_login_token("token", 7, 2, 100)
    query, params = conn.cur.executed[0]
    assert query.count("%s") == len(params)
    assert "AND club_id = %s AND is_confirmed = 0 AND expires_at > UTC_TIMESTAMP()" in query
    assert conn.committed


@pytest.mark.parametrize("delivery_fails", [False, True])
def test_yes_submits_for_admin_review_without_authenticating(monkeypatch, delivery_fails):
    live_token(monkeypatch)
    update, context = update_and_context("confirm")
    context.user_data["phone_link"]["guest"] = {"guest_id": 7, "phone": "9270086145"}
    update.callback_query.data = "lg_link:abc:yes"
    conn = Connection([{"cm_bonus_admin_chat_id": "-200"}])
    monkeypatch.setattr(flow, "get_db_connection", lambda: conn)
    monkeypatch.setattr(flow, "CM_BONUS_BOT_TOKEN", "test-token")
    created = []
    failed = []
    monkeypatch.setattr(flow, "create_link_request", lambda *args: created.append(args) or 42)
    monkeypatch.setattr(flow, "mark_notification_failed", lambda request_id: failed.append(request_id))
    admin_bot = AsyncMock()
    admin_bot.__aenter__.return_value = admin_bot
    if delivery_fails:
        admin_bot.send_message.side_effect = RuntimeError("Telegram offline")
    monkeypatch.setattr(flow, "_bot", lambda *args: admin_bot)
    complete = AsyncMock()
    monkeypatch.setattr(guest_bot, "complete_guest_login", complete)
    asyncio.run(flow.phone_choice_callback(update, context))
    assert created == [(2, 7, 100, "79990000000", "9270086145", "-200")]
    assert failed == ([42] if delivery_fails else [])
    complete.assert_not_called()
    assert "phone_link" not in context.user_data
    notification = admin_bot.send_message.call_args.kwargs
    assert notification["chat_id"] == "-200"
    assert "79990000000" not in notification["text"]
    assert "9270086145" not in notification["text"]


def test_unmatched_own_contact_offers_both_choices(monkeypatch):
    live_token(monkeypatch)
    update, context = update_and_context()
    update.message.contact = SimpleNamespace(user_id=100, phone_number="79990000000")
    monkeypatch.setattr(guest_bot, "find_guest_by_phone", lambda *args: (None, 0))
    asyncio.run(guest_bot.handle_contact(update, context))
    buttons = update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "Мой номер Telegram не совпадает с номером в LG"
    assert buttons[1][0].text == "Это точно мой номер"


def test_changed_admin_chat_cannot_review_old_request(monkeypatch):
    conn = Connection([{"club_id": 2}, {"club_id": 2}, request_row(), {"cm_bonus_admin_chat_id": "-300"}])
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    with pytest.raises(ValueError, match="текущем чате"):
        service.review_link_request(42, -200, 55, True)
    assert conn.rolled_back
