from datetime import datetime
from decimal import Decimal
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
    assert 'data-bonus-editor-only="wheel" hidden' in html
    assert 'data-bonus-editor-panel="wheel" hidden' in html
    assert 'data-bonus-editor-panel="cases" >' in html
    assert 'data-bonus-editor-switch="cases" class="is-active"' in html


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
    assert "openCaseAddModal" in html
    assert 'data-bonus-editor-panel="wheel" >' in html
    assert 'data-bonus-editor-panel="cases" hidden' in html
    assert "history.replaceState" in html
    assert 'href="/owner/settings?tab=wheel&amp;editor=' not in html


def test_bonus_settings_defaults_editor_to_active_game_mode():
    with app.test_request_context("/owner/settings?tab=wheel"):
        html = render_template(
            "owner/_settings_wheel.html",
            wheel_settings=SimpleNamespace(tokens_start_date=None, spin_cost=2, is_enabled=True),
            prizes=[],
            wheel_active_prob_sum=0,
            prize_icon_choices=["gift"],
            game_mode="cases",
            cases=[],
            case_upload_usage=None,
        )

    assert 'data-bonus-editor-switch="cases" class="is-active"' in html
    assert 'data-bonus-editor-panel="wheel" hidden' in html
    assert 'data-bonus-editor-panel="cases" >' in html


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
            },
            welcome_reward_settings={
                "welcome_reward_enabled": 1,
                "welcome_cm_bonus_amount": 200,
                "welcome_token_amount": 2,
            },
            topup_bonus_variables=[("first_name", "Имя"), ("bonus_amount", "Начислено КБ")],
            topup_bonus_exclude_from_amount=30000,
            topup_bonus_max_rule_amount=29999.99,
            promotions_only=True,
        )

    assert "Бонусы за пополнения" in html
    assert 'name="min_amount"' in html
    assert 'name="bonus_amount"' in html
    assert 'name="reward_type"' in html
    assert 'action="/owner/settings/welcome-reward"' in html
    assert 'name="cm_bonus_amount"' in html
    assert 'name="token_amount"' in html
    assert 'value="200"' in html
    assert 'value="2"' in html
    assert "Приветственная награда" in html
    assert html.index("Бонусы за пополнения") < html.index('id="welcome-reward"')
    assert "Редактор механики" not in html
    assert "Призы колеса" not in html
    assert html.count('class="settings-toggle') >= 3
    assert "Добавить правило" in html
    assert "{first_name}" in html
    assert "{bonus_amount}" in html
    assert 'id="topupBonusVariable"' in html
    assert 'id="insertTopupBonusVariable"' in html
    assert 'max="29999.99"' in html
    assert "Пополнения от 30000 ₽ не участвуют" in html


def test_promotions_page_contains_only_promotion_settings():
    with app.test_request_context("/owner/promotions"):
        html = render_template(
            "owner/promotions.html",
            topup_bonus_settings={"is_enabled": 0, "message_template": "Текст", "rules": []},
            welcome_reward_settings={
                "welcome_reward_enabled": 1,
                "welcome_cm_bonus_amount": 0,
                "welcome_token_amount": 1,
            },
            topup_bonus_variables=[],
            topup_bonus_exclude_from_amount=30000,
            topup_bonus_max_rule_amount=29999.99,
            topup_bonus_approvals=[
                {
                    "id": 41,
                    "topup_amount": Decimal("1500.00"),
                    "topup_at": datetime(2026, 9, 21, 12, 30),
                    "guest_id": 15173,
                    "fio": "Морозов Дмитрий Антонович",
                    "phone": "79990000000",
                    "bonus_amount": 300,
                    "reward_type": "cm_bonus",
                    "rule_min_amount": Decimal("1000.00"),
                    "status": "pending_approval",
                    "reviewed_at": None,
                }
            ],
        )

    assert "<h1>Акции</h1>" in html
    assert "Бонусы за пополнения" in html
    assert "Подтверждение бонусов за пополнение" in html
    assert "Морозов Дмитрий Антонович" in html
    assert 'action="/owner/settings/topup-bonuses/41/review"' in html
    assert 'value="approve"' in html
    assert 'value="reject"' in html
    assert "Приветственная награда" in html
    assert "Редактор механики" not in html
    assert "Призы колеса" not in html


def test_bonus_settings_summary_only_contains_case_and_wheel_configuration():
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
    assert "Приветственная награда" not in html
    assert "Показывать призы только моего клуба" in html
    assert "Лента призов" in html
    assert "Только клуб" in html
    assert "Начислять жетоны за посещения" in html
    assert 'data-bonus-editor-only="wheel" hidden' in html
    assert "Колесо включено" not in html


def test_case_settings_use_guest_style_cards_with_config_modals():
    cases = [
        {
            "id": 42,
            "name": "Золотой кейс",
            "badge_label": "Редкий",
            "badge_color": "#FFD469",
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
    assert "case-workspace-layout" in html
    assert "Предпросмотр кейса" in html
    assert 'data-case-items-table="42"' in html
    assert 'data-case-inline-form' in html
    assert 'form="case-inline-item-7"' in html
    assert "Основные значения можно менять прямо в таблице" in html
    assert 'data-open-case-item-add="caseItemAddDialog42"' in html
    assert 'id="caseItemAddDialog42"' in html
    assert 'data-case-item-add-dialog' in html
    assert 'data-case-workspace-tab' not in html
    assert "Добавить предмет в кейс" not in html
    assert 'class="case-toggle case-toggle--case" for="case_active_42"' in html
    assert 'class="case-toggle case-table-toggle"' in html
    assert 'class="case-toggle__track"' in html
    assert 'class="case-preview-card__price-text"' in html
    assert "Каждый кейс открывается за жетоны" not in html
    assert 'name="remove_image"' not in html
    assert 'data-case-cover-url' not in html
    assert 'type="hidden" name="image_url"' in html
    assert 'name="badge_label"' in html
    assert 'name="badge_color"' in html
    assert 'type="color"' in html
    assert 'value="#FFD469"' in html
    assert "--case-badge-color: #FFD469" in html
    assert "document.body.style.overflow = 'hidden'" in html
    assert "modal.addEventListener('wheel', stopModalBackgroundScroll" in html
    assert "data-case-item-form data-no-loading" in html
    assert "data-case-item-add-form data-no-loading" in html
    assert "data-case-item-delete data-no-loading" in html
