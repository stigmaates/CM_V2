from datetime import datetime

from app.services.cm_bonuses import format_cm_bonus_redeem_message


def test_credited_redeem_message_uses_club_local_time():
    message = format_cm_bonus_redeem_message(
        {
            "id": 17,
            "club_id": 3,
            "guest_id": 42,
            "guest_name": "Иван Иванов",
            "guest_phone": "79990000000",
            "amount": 150,
            "status": "credited",
            "processed_by_username": "@SharoutUfaClub",
            "processed_at": datetime(2026, 8, 25, 14, 18),
            "club_timezone": "Asia/Yekaterinburg",
        },
        credited=True,
    )

    assert "Дата зачисления (время клуба): <b>25.08.2026 19:18</b>" in message
