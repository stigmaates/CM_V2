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
