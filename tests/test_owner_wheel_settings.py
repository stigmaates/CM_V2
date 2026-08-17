from flask import session

from app.main import app
from app.routes.owner import wheel as owner_wheel


def test_owner_wheel_settings_does_not_validate_wheel_prizes_in_cases_mode(monkeypatch):
    validated = []
    saved = []

    monkeypatch.setattr(owner_wheel, "get_game_mode", lambda club_id: "cases")
    monkeypatch.setattr(
        owner_wheel,
        "assert_active_wheel_probabilities_sum_is_100",
        lambda club_id: validated.append(club_id),
    )
    monkeypatch.setattr(
        owner_wheel,
        "save_wheel_settings",
        lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(owner_wheel, "record_audit_event", lambda **kwargs: None)

    with app.test_request_context(
        "/owner/wheel",
        method="POST",
        data={
            "tokens_start_date": "2026-08-17T12:00",
            "spin_cost": "2",
            "is_enabled": "1",
            "show_only_own_valuable_drops": "1",
            "bonus_editor": "cases",
        },
    ):
        session["user_id"] = 1
        session["role"] = "owner"
        session["club_id"] = 1

        response = owner_wheel.wheel_settings()

    assert response.status_code == 302
    assert "editor=cases" in response.location
    assert validated == []
    assert saved[0]["is_enabled"] == 1
    assert saved[0]["show_only_own_valuable_drops"] == 1
