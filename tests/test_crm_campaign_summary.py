from app.services.mailing import _campaign_effect_summary


def test_campaign_summary_counts_unique_guests_and_used_bonus_ratio():
    summary = _campaign_effect_summary(
        {"recipients_count": 1, "bonus_amount": 0, "token_amount": 0},
        [
            {
                "guest_id": 101,
                "delivery_status": "sent",
                "next_visit_at": "2026-08-01 12:00:00",
                "topup_amount_after": 500,
                "used_bonus_after": 50,
            },
            {
                "guest_id": 101,
                "delivery_status": "sent",
                "next_visit_at": "2026-08-01 12:00:00",
                "topup_amount_after": 500,
                "used_bonus_after": 50,
            },
        ],
    )

    assert summary["recipients_count"] == 1
    assert summary["delivered_count"] == 1
    assert summary["visited_count"] == 1
    assert summary["topped_up_count"] == 1
    assert summary["topup_amount"] == 500
    assert summary["used_bonus"] == 50
    assert summary["topup_per_bonus"] == 10
