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
        },
    ):
        session.update(user_id=1, role="owner", club_id=7)
        response = owner_mailing.api_auto_mailing_toggle("inactive_14_bonus")

    assert response.status_code == 200
    assert response.get_json()["auto_mailing"]["send_start_time"] == "09:15"
    assert saved[0][2]["send_start_time"] == "09:15"
    assert saved[0][2]["send_end_time"] == "21:45"
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
