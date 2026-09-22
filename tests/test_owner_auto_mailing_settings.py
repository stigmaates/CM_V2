from flask import session

from app.main import app
from app.routes.owner import mailing as owner_mailing


class _Connection:
    def __init__(self):
        self.committed = False
        self.closed = False

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True

    def rollback(self):
        pass


def test_owner_can_save_club_local_auto_mailing_window(monkeypatch):
    conn = _Connection()
    saved = []
    monkeypatch.setattr(owner_mailing, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        owner_mailing,
        "update_auto_mailing_settings",
        lambda _conn, club_id, code, **kwargs: saved.append((club_id, code, kwargs))
        or {"code": code, **kwargs},
    )

    with app.test_request_context(
        "/owner/api/auto-mailings/inactive_14_bonus/toggle",
        method="POST",
        json={
            "is_enabled": True,
            "send_start_time": "09:15",
            "send_end_time": "21:45",
            "smart_inactive_enabled": True,
            "smart_inactive_days": 21,
            "smart_interval_multiplier": 3,
        },
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response = owner_mailing.api_auto_mailing_toggle("inactive_14_bonus")

    assert response.status_code == 200
    assert response.get_json()["auto_mailing"]["send_start_time"] == "09:15"
    assert saved[0][2]["send_start_time"] == "09:15"
    assert saved[0][2]["send_end_time"] == "21:45"
    assert saved[0][2]["smart_inactive_enabled"] is True
    assert saved[0][2]["smart_inactive_days"] == 21
    assert saved[0][2]["smart_interval_multiplier"] == 3
    assert conn.committed is True
    assert conn.closed is True


def test_owner_cannot_save_empty_auto_mailing_window():
    with app.test_request_context(
        "/owner/api/auto-mailings/inactive_14_bonus/toggle",
        method="POST",
        json={
            "is_enabled": True,
            "send_start_time": "10:00",
            "send_end_time": "10:00",
        },
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response, status = owner_mailing.api_auto_mailing_toggle("inactive_14_bonus")

    assert status == 400
    assert "должны отличаться" in response.get_json()["error"]


def test_owner_rejects_invalid_smart_interval_multiplier():
    with app.test_request_context(
        "/owner/api/auto-mailings/inactive_14_bonus/toggle",
        method="POST",
        json={"is_enabled": False, "smart_interval_multiplier": 0},
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response, status = owner_mailing.api_auto_mailing_toggle("inactive_14_bonus")

    assert status == 400
    assert "Множитель интервала" in response.get_json()["error"]


def test_stage_manual_mode_rejects_enabling_auto_mailing(monkeypatch):
    monkeypatch.setattr(owner_mailing, "manual_mailings_only", lambda: True)

    with app.test_request_context(
        "/owner/api/auto-mailings/inactive_14_bonus/toggle",
        method="POST",
        json={"is_enabled": True},
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response, status = owner_mailing.api_auto_mailing_toggle("inactive_14_bonus")

    assert status == 400
    assert response.get_json() == {
        "ok": False,
        "error": "На тестовом стенде разрешены только ручные рассылки",
    }


def test_unified_reward_mailing_forwards_attachments(monkeypatch):
    conn = _Connection()
    calls = []
    started = []
    monkeypatch.setattr(owner_mailing, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        owner_mailing,
        "create_bonus_giveaway",
        lambda **kwargs: calls.append(kwargs)
        or {"giveaway_id": 4, "mailing_id": 9, "recipients_count": 2},
    )
    monkeypatch.setattr(owner_mailing, "_start_mailing_worker", started.append)

    attachments = [
        {
            "file_type": "photo",
            "file_path": "/tmp/example.jpg",
            "original_name": "example.jpg",
        }
    ]
    with app.test_request_context(
        "/owner/api/bonus-giveaways/create",
        method="POST",
        json={
            "rules": [],
            "bonus_amount": 200,
            "token_amount": 1,
            "message_text": "Привет!",
            "attachments": attachments,
            "logic": "or",
            "start_now": True,
        },
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response = owner_mailing.api_bonus_giveaways_create()

    assert response.status_code == 200
    assert calls[0]["attachments"] == attachments
    assert calls[0]["logic"] == "and"
    assert calls[0]["club_id"] == 7
    assert started == [9]
    assert conn.committed is True
    assert conn.closed is True


def test_blocked_stage_mailing_returns_json_error(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(owner_mailing, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        owner_mailing,
        "create_mailing",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("Исходящие сообщения отключены на тестовом стенде")
        ),
    )

    with app.test_request_context(
        "/owner/api/mailings/create",
        method="POST",
        json={"rules": [], "message_text": "Проверка", "attachments": []},
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response, status = owner_mailing.api_mailings_create()

    assert status == 400
    assert response.is_json
    assert response.get_json() == {
        "ok": False,
        "error": "Исходящие сообщения отключены на тестовом стенде",
    }
    assert conn.committed is False
    assert conn.closed is True
