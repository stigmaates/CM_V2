from flask import session

from app.core import guest_required
from app.main import app
from app.services import guest_management


def test_banned_guest_api_receives_json_and_cannot_continue(monkeypatch):
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: True)

    @guest_required
    def protected_api():
        raise AssertionError("banned guest must not reach the endpoint")

    with app.test_request_context("/guest/api/tokens"):
        session["guest_logged_in"] = True
        session["guest_id"] = 10
        session["guest_club_id"] = 2
        response, status = protected_api()

    assert status == 403
    assert response.get_json()["error"] == "guest_banned"


def test_banned_guest_page_shows_administration_message(monkeypatch):
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: True)

    @guest_required
    def protected_page():
        raise AssertionError("banned guest must not reach the endpoint")

    with app.test_request_context("/guest/dashboard"):
        session["guest_logged_in"] = True
        session["guest_id"] = 10
        session["guest_club_id"] = 2
        response, status = protected_page()

    assert status == 403
    assert "обратитесь к администрации клуба" in response.lower()
