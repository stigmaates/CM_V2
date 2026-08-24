from types import SimpleNamespace

from flask import render_template

from app.main import app


def test_bonus_settings_shows_case_editor_while_wheel_mode_is_active():
    with app.test_request_context("/owner/settings?tab=wheel&editor=cases"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="wheel",
            bonus_editor="cases",
            cases=[],
            case_upload_usage=None,
        )

    assert "Колесо фортуны" in html
    assert "Кейсы" in html
    assert "openCaseAddModal" in html
    assert "Добавить кейс" in html
    assert "Стоимость прокрута колеса" not in html
    assert 'type="hidden" name="spin_cost"' in html
    assert "Призы колеса" not in html


def test_bonus_settings_shows_wheel_editor_by_default():
    with app.test_request_context("/owner/settings?tab=wheel"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="wheel",
            bonus_editor="wheel",
            cases=[],
            case_upload_usage=None,
        )

    assert "Призы колеса" in html
    assert "openPrizeAddModal" in html
    assert "openCaseAddModal" not in html


def test_bonus_settings_shows_configurable_topup_rewards():
    with app.test_request_context("/owner/settings?tab=wheel"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="wheel",
            bonus_editor="wheel",
            cases=[],
            case_upload_usage=None,
            topup_bonus_settings={
                "is_enabled": 1,
                "message_template": "{first_name}: +{bonus_amount} КБ",
                "rules": [{"min_amount": 1000, "bonus_amount": 300, "reward_type": "tokens"}],
                "welcome_reward_enabled": 1,
                "welcome_reward_type": "cm_bonus",
                "welcome_reward_amount": 200,
            },
            topup_bonus_variables=[("first_name", "Имя"), ("bonus_amount", "Начислено КБ")],
            topup_bonus_exclude_from_amount=30000,
            topup_bonus_max_rule_amount=29999.99,
        )

    assert "Бонусы за пополнения" in html
    assert 'name="min_amount"' in html
    assert 'name="bonus_amount"' in html
    assert 'name="reward_type"' in html
    assert 'name="welcome_reward_type"' in html
    assert 'name="welcome_reward_amount"' in html
    assert 'value="200"' in html
    assert "Добавить правило" in html
    assert "{first_name}" in html
    assert "{bonus_amount}" in html
    assert 'id="topupBonusVariable"' in html
    assert 'id="insertTopupBonusVariable"' in html
    assert 'max="29999.99"' in html
    assert "Пополнения от 30000 ₽ не участвуют" in html


def test_bonus_settings_token_summary_uses_shared_token_language():
    with app.test_request_context("/owner/settings?tab=wheel"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(
                tokens_start_date=None,
                spin_cost=2,
                is_enabled=True,
                show_only_own_valuable_drops=True,
            ),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="cases",
            bonus_editor="cases",
            cases=[],
            case_upload_usage=None,
        )

    assert "Активный режим" in html
    assert "Старт жетонов" in html
    assert "За первое посещение" in html
    assert "Показывать призы только моего клуба" in html
    assert "Лента призов" in html
    assert "Только клуб" in html
    assert "+1 жетон" in html
    assert "Начислять жетоны за посещения" in html
    assert "Стоимость прокрута колеса" not in html
    assert "Колесо включено" not in html


def test_case_settings_use_guest_style_cards_with_config_modals():
    cases = [
        {
            "id": 42,
            "name": "Золотой кейс",
            "badge_label": "Редкий",
            "description": "Премиальные призы",
            "image_url": "/static/uploads/cases/gold.webp",
            "price_tokens": 3,
            "is_active": True,
            "items": [
                {
                    "id": 7,
                    "name": "150 КБ",
                    "probability": 100,
                    "rarity_label": "Обычный",
                    "bonus_amount": 150,
                    "token_amount": 0,
                    "image_url": "",
                    "description": "",
                    "is_active": True,
                }
            ],
        }
    ]

    with app.test_request_context("/owner/settings?tab=wheel&editor=cases"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="cases",
            bonus_editor="cases",
            cases=cases,
            case_upload_usage=None,
        )

    assert "case-showcase-grid" in html
    assert "case-showcase-card" in html
    assert "/static/uploads/cases/gold.webp" in html
    assert 'data-open-case-config="caseConfigModal42"' in html
    assert 'id="caseConfigModal42"' in html
    assert "Настроить кейс: Золотой кейс" in html
    assert "document.body.style.overflow = 'hidden'" in html
    assert "modal.addEventListener('wheel', stopModalBackgroundScroll" in html
    assert "data-case-item-form data-no-loading" in html
    assert "data-case-item-add-form data-no-loading" in html
    assert "data-case-item-delete data-no-loading" in html
