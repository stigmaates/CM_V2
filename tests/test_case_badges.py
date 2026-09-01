import pytest
from flask import render_template

from app.main import app
from app.services.cases import (
    DEFAULT_CASE_BADGE_COLOR,
    normalize_case_badge_color,
    serialize_case,
    validate_case_badge_color,
)


def test_case_badge_color_validation_and_normalization():
    assert validate_case_badge_color("#ffd469") == "#FFD469"
    assert validate_case_badge_color("") == DEFAULT_CASE_BADGE_COLOR
    assert normalize_case_badge_color("not-a-color") == DEFAULT_CASE_BADGE_COLOR

    with pytest.raises(ValueError, match="#RRGGBB"):
        validate_case_badge_color("gold")


def test_serialized_case_contains_safe_badge_color():
    case = serialize_case(
        {
            "id": 7,
            "name": "CS2 Case",
            "badge_label": "x2 шанс редкого",
            "badge_color": "#ffd469",
            "price_tokens": 2,
            "items": [],
        }
    )

    assert case["badge_label"] == "x2 шанс редкого"
    assert case["badge_color"] == "#FFD469"


def test_guest_case_card_renders_badge_text_and_color():
    with app.test_request_context("/guest/dashboard"):
        html = render_template(
            "guest/guest_dashboard.html",
            guest_name="Иван",
            profile_stats={"total_hours": 0},
            guest_missions=[],
            wheel_settings={"spin_cost": 2},
            wheel_prizes=[],
            game_mode="cases",
            cases=[
                {
                    "id": 7,
                    "name": "CS2 Case",
                    "description": "Игровые призы",
                    "image_url": None,
                    "badge_label": "x2 шанс редкого",
                    "badge_color": "#FFD469",
                    "price_tokens": 2,
                    "items": [],
                }
            ],
            valuable_case_drops=[],
            token_balance=5,
            reward_history=[],
            streak_info={},
            cm_bonus_balance=0,
            cm_bonus_history=[],
            cm_bonus_redeem_history=[],
        )

    assert "x2 шанс редкого" in html
    assert 'class="case-tile-badge"' in html
    assert "--case-badge-color: #FFD469" in html
    assert "const syncedPanelBottomInset = 12" in html
    assert 'class="case-tile-desc"' not in html
    assert 'class="cases-subtitle cases-subtitle--footer"' not in html
    assert "Открывай кейсы и получай призы" not in html
    assert "casesGrid.style.flex = syncCasesToProfile ? '1 1 auto'" in html
