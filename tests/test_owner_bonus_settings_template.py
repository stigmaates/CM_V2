from types import SimpleNamespace

from flask import render_template

from app.main import app


def test_bonus_settings_shows_case_editor_while_wheel_mode_is_active():
    with app.test_request_context("/owner/settings?tab=wheel"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="wheel",
            cases=[],
            case_upload_usage=None,
        )

    assert "Колесо фортуны" in html
    assert "Кейсы" in html
    assert "openCaseAddModal" in html
    assert "Добавить кейс" in html
