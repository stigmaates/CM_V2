from app.services.mailing import (
    _campaign_effect_summary,
    _deduplicate_interaction_recipients,
    _fetch_campaign_effect_rows,
)


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


def test_interaction_recipients_deduplicate_grouped_auto_mailings_by_guest():
    rows = [
        {
            "recipient_id": 20,
            "guest_id": 101,
            "delivery_status": "sent",
            "interaction_at": "2026-08-10 06:05:00",
            "next_visit_at": None,
        },
        {
            "recipient_id": 21,
            "guest_id": 101,
            "delivery_status": "sent",
            "interaction_at": "2026-08-10 06:10:00",
            "next_visit_at": None,
        },
        {
            "recipient_id": 22,
            "guest_id": 102,
            "delivery_status": "failed",
            "interaction_at": "2026-08-10 06:05:00",
            "next_visit_at": None,
        },
    ]

    deduplicated = _deduplicate_interaction_recipients(rows)

    assert len(deduplicated) == 2
    assert [row["guest_id"] for row in deduplicated] == [101, 102]
    assert deduplicated[0]["recipient_id"] == 20


class _Cursor:
    def __init__(self):
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()

    def cursor(self):
        return self.cursor_obj


def test_campaign_effect_rows_select_next_collapsed_visit_start():
    conn = _Connection()

    _fetch_campaign_effect_rows(conn, club_id=1, mailing_ids=[10], giveaway_id=None)

    assert "NOT EXISTS" in conn.cursor_obj.query
    assert "DATE_ADD(prev.date_stop, INTERVAL 2 HOUR)" in conn.cursor_obj.query
