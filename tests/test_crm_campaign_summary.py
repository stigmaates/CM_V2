from datetime import datetime

import app.services.mailing as mailing_service
from app.services.mailing import (
    _campaign_effect_summary,
    _deduplicate_interaction_recipients,
    _fetch_campaign_effect_rows,
    _json_row,
    _summarize_auto_crm_events,
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


class _InteractionCursor(_Cursor):
    def __init__(self):
        super().__init__()
        self.queries = []

    def execute(self, query, params=None):
        super().execute(query, params)
        self.queries.append(query)

    def fetchone(self):
        if "SELECT timezone FROM clubs" in self.query:
            return {"timezone": "Asia/Yekaterinburg"}
        return {
            "interaction_id": 13,
            "interaction_type": "giveaway",
            "giveaway_id": 13,
            "mailing_id": 422,
            "status": "completed",
            "recipients_count": 0,
            "created_at": datetime(2026, 8, 26, 9, 55, 22),
        }


class _InteractionConnection:
    def __init__(self):
        self.cursor_obj = _InteractionCursor()

    def cursor(self):
        return self.cursor_obj


def test_campaign_effect_rows_select_next_collapsed_visit_start():
    conn = _Connection()

    _fetch_campaign_effect_rows(conn, club_id=1, mailing_ids=[10], giveaway_id=None)

    assert "NOT EXISTS" in conn.cursor_obj.query
    assert "DATE_ADD(prev.date_stop, INTERVAL 2 HOUR)" in conn.cursor_obj.query
    assert "ON ns.club_id = m.club_id" in conn.cursor_obj.query
    assert "AND ns.guest_id = mr.guest_id" in conn.cursor_obj.query


def test_campaign_datetimes_are_serialized_in_club_timezone():
    row = _json_row(
        {
            "created_at": datetime(2026, 8, 26, 9, 59, 36),
            "next_visit_at": datetime(2026, 8, 27, 8, 0),
            "message_text": "Тест",
        },
        timezone_name="Asia/Yekaterinburg",
    )

    assert row == {
        "created_at": "2026-08-26 14:59:36",
        "next_visit_at": "2026-08-27 13:00:00",
        "message_text": "Тест",
    }


def test_interaction_visit_joins_are_scoped_to_club_and_guest(monkeypatch):
    monkeypatch.setattr(mailing_service, "ensure_bonus_giveaway_tables", lambda conn: None)
    conn = _InteractionConnection()

    mailing_service.get_crm_interaction_detail(conn, 3, "giveaway", 13)

    recipients_query = next(query for query in conn.cursor_obj.queries if "LEFT JOIN guest_sessions ps" in query)
    assert "ON ps.club_id = m.club_id" in recipients_query
    assert "AND ps.guest_id = mr.guest_id" in recipients_query
    assert "ON ns.club_id = m.club_id" in recipients_query
    assert "AND ns.guest_id = mr.guest_id" in recipients_query


def test_auto_campaign_summary_uses_unique_events_and_next_collapsed_visit_topups():
    events = [
        {
            "automation_code": "inactive_return",
            "title": "Вернуть после неактива",
            "guest_id": 101,
            "interaction_at": datetime(2026, 8, 1, 10, 0),
        },
        {
            "automation_code": "inactive_return",
            "title": "Вернуть после неактива",
            "guest_id": 102,
            "interaction_at": datetime(2026, 8, 1, 10, 0),
        },
    ]
    sessions = [
        {
            "guest_id": 101,
            "date_start": datetime(2026, 8, 3, 12, 0),
            "date_stop": datetime(2026, 8, 3, 13, 0),
        },
        {
            "guest_id": 101,
            "date_start": datetime(2026, 8, 3, 14, 30),
            "date_stop": datetime(2026, 8, 3, 16, 0),
        },
        {
            "guest_id": 102,
            "date_start": datetime(2026, 9, 5, 12, 0),
            "date_stop": datetime(2026, 9, 5, 13, 0),
        },
    ]
    topups = [
        {"guest_id": 101, "amount": 500, "topup_at": datetime(2026, 8, 3, 15, 0)},
        {"guest_id": 101, "amount": 700, "topup_at": datetime(2026, 8, 4, 15, 0)},
    ]

    result = _summarize_auto_crm_events(events, sessions, topups)

    assert result == [
        {
            "code": "inactive_return",
            "title": "Вернуть после неактива",
            "unique_recipients": 2,
            "returned_count": 1,
            "conversion_percent": 50.0,
            "topped_up_count": 1,
            "topup_amount": 500.0,
        }
    ]
