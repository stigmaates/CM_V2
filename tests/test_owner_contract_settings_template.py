from flask import render_template

from app.main import app


def _rewards():
    return {
        "easy": {"difficulty_label": "Лёгкий", "reward_tokens": 1, "reward_bonus": 0},
        "medium": {"difficulty_label": "Средний", "reward_tokens": 2, "reward_bonus": 100},
        "hard": {"difficulty_label": "Сложный", "reward_tokens": 3, "reward_bonus": 200},
    }


def test_contract_settings_render_enabled_feature_toggle():
    with app.test_request_context("/owner/settings?tab=contracts"):
        html = render_template(
            "owner/_settings_contracts.html",
            contract_reward_settings=_rewards(),
            contract_feature_settings={"is_enabled": True},
        )

    assert 'name="contracts_enabled"' in html
    assert 'name="contracts_enabled" value="1" checked' in html
    assert "Механика включена" in html
    assert "Сохранить настройки" in html
