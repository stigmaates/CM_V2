from flask import render_template

from app.main import app


def test_auto_mailing_card_renders_its_club_local_send_window():
    with app.test_request_context("/owner/mailing"):
        html = render_template(
            "owner/mailing.html",
            filter_fields=[],
            message_variables=[],
            crm_segments=[],
            segments=[],
            mailings=[],
            auto_mailings=[
                {
                    "code": "inactive_14_bonus",
                    "title": "Вернуть гостя",
                    "description": "Описание",
                    "message_text": "Привет!",
                    "days_inactive": 14,
                    "smart_inactive_enabled": 1,
                    "smart_inactive_days": 21,
                    "smart_interval_multiplier": 3,
                    "bonus_amount": 200,
                    "delay_minutes": None,
                    "send_start_time": "09:15",
                    "send_end_time": "21:45",
                    "is_enabled": 1,
                }
            ],
            club_timezone_label="Самара — UTC+4",
            bonus_giveaways=[],
            crm_interactions=[],
        )

    assert "Используется время клуба: Самара — UTC+4" in html
    assert 'class="auto-mailing-send-start"' in html
    assert 'value="09:15"' in html
    assert 'class="auto-mailing-send-end"' in html
    assert 'value="21:45"' in html
    assert 'class="auto-mailing-smart-toggle"' in html
    assert 'class="auto-mailing-smart-days"' in html
    assert 'value="21"' in html
    assert 'class="auto-mailing-smart-multiplier"' in html
    assert "Уверенность 50+" in html


def test_manual_mailing_uses_one_audience_message_and_reward_form():
    with app.test_request_context("/owner/mailing"):
        html = render_template(
            "owner/mailing.html",
            filter_fields=[],
            message_variables=[],
            crm_segments=[
                {
                    "key": "loyal",
                    "title": "Лояльное ядро",
                    "emoji": "👑",
                    "description": "Стабильно посещают клуб",
                    "rules": {"rules": [{"field": "guest_pulse_audience", "op": "=", "value": "loyal"}]},
                }
            ],
            segments=[],
            mailings=[],
            auto_mailings=[],
            club_timezone_label="Москва — UTC+3",
            bonus_giveaways=[],
            crm_interactions=[],
        )

    assert html.count('id="rulesContainer"') == 1
    assert html.count('id="messageText"') == 1
    assert 'id="giveawayBonusEnabled"' in html
    assert 'id="giveawayTokenEnabled"' in html
    assert 'id="sendMailingBtn"' in html
    assert "Группы из Пульса гостя" in html
    assert "Лояльное ядро" in html
    assert "Стабильно посещают клуб" not in html
    assert "чел." not in html.split("Конструктор аудитории", 1)[0]
    assert 'data-audience-logic=' not in html
    assert "Пересчитать аудиторию" not in html
    assert 'id="previewBtn">Применить</button>' in html
    assert "Сохранить как сегмент" not in html
    assert 'id="segmentName" placeholder="Название сегмента"' in html
    assert "Добавить ссылку" in html
    assert 'Фильтры раздачи' not in html
    assert 'Отправить раздачу' not in html
