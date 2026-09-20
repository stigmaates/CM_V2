from datetime import datetime

from flask import render_template

from app.main import app
from app.services import missions as missions_service


def test_mission_settings_render_compact_cards_and_edit_modal():
    mission = {
        "id": 17,
        "mission_template_id": 3,
        "display_name": "Ночная лига",
        "name": "Ночные визиты",
        "custom_name": "Ночная лига",
        "custom_description": "Посети клуб четыре раза ночью",
        "target_amount": 4,
        "target_label": "Количество визитов",
        "target_hint": "",
        "reward_text": "Приз",
        "token_reward": 3,
        "cm_bonus_reward": 150,
        "start_at": datetime(2026, 9, 20, 10, 0),
        "end_at": datetime(2026, 10, 20, 10, 0),
        "is_enabled": True,
        "status": "active",
        "status_label": "Активно",
        "config": {},
        "requires_min_hours": False,
        "requires_case_select": False,
        "requires_time_range": False,
    }

    with app.test_request_context("/owner/settings?tab=missions"):
        html = render_template(
            "owner/_settings_missions.html",
            missions=[mission],
            templates=[],
            active_cases=[],
            club_timezone_label="Москва — UTC+3",
        )

    assert 'data-mission-view="grid"' in html
    assert 'data-mission-view="list"' in html
    assert 'data-mission-status="active"' in html
    assert 'data-mission-modal-open="missionEditModal17"' in html
    assert 'id="missionEditModal17" data-mission-modal' in html
    assert 'id="missionEditForm17"' in html
    assert "Добавить задание" in html
    assert "Посети клуб четыре раза ночью" in html


def test_mission_settings_empty_state_keeps_prominent_add_action():
    with app.test_request_context("/owner/settings?tab=missions"):
        html = render_template(
            "owner/_settings_missions.html",
            missions=[],
            templates=[],
            active_cases=[],
            club_timezone_label="Москва — UTC+3",
        )

    assert 'class="missions-add-trigger"' in html
    assert "Добавьте первое" in html


def test_mission_statuses_are_derived_in_club_local_time(monkeypatch):
    now = datetime(2026, 9, 20, 12, 0)
    monkeypatch.setattr(missions_service, "get_club_local_now", lambda _timezone: now)

    def enrich(*, enabled=True, start_at=None, end_at=None):
        return missions_service._enrich_mission_row(
            {
                "config": None,
                "config_schema": None,
                "custom_name": None,
                "name": "Задание",
                "target_metric": "visits_count",
                "club_timezone": "Europe/Moscow",
                "is_enabled": enabled,
                "start_at": start_at,
                "end_at": end_at,
            }
        )

    assert enrich()["status"] == "active"
    assert enrich(start_at=datetime(2026, 9, 21, 12, 0))["status"] == "scheduled"
    assert enrich(end_at=datetime(2026, 9, 19, 12, 0))["status"] == "completed"
    assert enrich(enabled=False)["status"] == "completed"
