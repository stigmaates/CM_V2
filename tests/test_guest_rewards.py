from datetime import datetime, timedelta

from app.services.guest_rewards import combine_guest_reward_history


def test_combined_reward_history_includes_mission_token_and_bonus_rewards():
    now = datetime(2026, 8, 17, 12, 0, 0)

    rewards = combine_guest_reward_history(
        token_rows=[
            {
                "id": 10,
                "amount": 3,
                "balance_after": 8,
                "source_type": "mission",
                "source_id": "7",
                "description": "Задание выполнено: Марафончик",
                "created_at": now,
            },
            {
                "id": 9,
                "amount": -1,
                "balance_after": 5,
                "source_type": "wheel_spin",
                "source_id": "100",
                "description": "Прокрут колеса фортуны",
                "created_at": now - timedelta(minutes=1),
            },
        ],
        bonus_rows=[
            {
                "id": 11,
                "amount": 100,
                "balance_after": 260,
                "source_type": "mission",
                "source_id": "7",
                "description": "Задание выполнено: Летние каникулы",
                "status": "done",
                "created_at": now - timedelta(minutes=2),
            }
        ],
        case_rows=[],
        wheel_rows=[],
        limit=10,
    )

    assert [item["amount_label"] for item in rewards] == ["+3 жет.", "+100 КБ"]
    assert rewards[0]["title"] == "Задание выполнено: Марафончик"
    assert rewards[1]["title"] == "Задание выполнено: Летние каникулы"


def test_combined_reward_history_keeps_physical_case_prizes_without_double_counting_auto_rewards():
    now = datetime(2026, 8, 17, 12, 0, 0)

    rewards = combine_guest_reward_history(
        token_rows=[],
        bonus_rows=[],
        case_rows=[
            {
                "opening_id": 42,
                "created_at": now,
                "case_name": "CS2 Case",
                "name": "Клавиатура",
                "image_url": "/uploads/cases/keyboard.webp",
                "bonus_amount": 0,
                "token_amount": 0,
                "claim_status": "notified",
            },
            {
                "opening_id": 43,
                "created_at": now + timedelta(minutes=1),
                "case_name": "CS2 Case",
                "name": "25 КБ",
                "image_url": None,
                "bonus_amount": 25,
                "token_amount": 0,
                "claim_status": None,
            },
        ],
        wheel_rows=[],
        limit=10,
    )

    assert len(rewards) == 1
    assert rewards[0]["title"] == "Клавиатура"
    assert rewards[0]["amount_label"] == "приз"
    assert rewards[0]["status_class"] == "pending"
