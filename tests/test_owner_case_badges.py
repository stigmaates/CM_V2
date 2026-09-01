from flask import session

from app.main import app
from app.routes.owner import cases as owner_cases


def _owner_session():
    session["user_id"] = 1
    session["role"] = "owner"
    session["club_id"] = 2


def test_owner_can_create_case_with_badge_text_and_color(monkeypatch):
    created = []
    monkeypatch.setattr(owner_cases, "_get_uploaded_image_url", lambda **kwargs: None)
    monkeypatch.setattr(owner_cases, "get_cases_for_admin", lambda club_id: [])
    monkeypatch.setattr(owner_cases, "create_case", lambda **kwargs: created.append(kwargs) or 42)
    monkeypatch.setattr(owner_cases, "record_audit_event", lambda **kwargs: None)

    with app.test_request_context(
        "/owner/cases/add",
        method="POST",
        data={
            "name": "CS2 Case",
            "badge_label": "x2 шанс редкого",
            "badge_color": "#ffd469",
            "price_tokens": "3",
        },
    ):
        _owner_session()
        response = owner_cases.case_add()

    assert response.status_code == 302
    assert created[0]["badge_label"] == "x2 шанс редкого"
    assert created[0]["badge_color"] == "#FFD469"


def test_owner_case_rejects_invalid_badge_color(monkeypatch):
    created = []
    monkeypatch.setattr(owner_cases, "_get_uploaded_image_url", lambda **kwargs: None)
    monkeypatch.setattr(owner_cases, "create_case", lambda **kwargs: created.append(kwargs) or 42)

    with app.test_request_context(
        "/owner/cases/add",
        method="POST",
        data={
            "name": "CS2 Case",
            "badge_label": "x2 шанс редкого",
            "badge_color": "gold; background: red",
            "price_tokens": "3",
        },
    ):
        _owner_session()
        response = owner_cases.case_add()

    assert response.status_code == 302
    assert created == []
