from datetime import datetime

from app.services import cases


class _Cursor:
    def __init__(self):
        self.query = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params or ()

    def fetchall(self):
        return [
            {
                "opening_id": 10,
                "created_at": datetime(2026, 8, 17, 12, 0),
                "guest_name": "Иванов Дмитрий",
                "club_name": "WALLZ",
                "case_name": "CS2 Case",
                "item_name": "Джерси",
                "item_description": "",
                "item_image_url": "",
                "rarity_label": "Редкий",
            }
        ]


class _Connection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


def test_valuable_case_drops_can_be_scoped_to_guest_club(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(cases, "ensure_case_tables", lambda _cursor: None)
    monkeypatch.setattr(cases, "ensure_prize_claim_tables", lambda _cursor: None)
    monkeypatch.setattr(cases, "get_db_connection", lambda: _Connection(cursor))

    drops = cases.get_valuable_case_drops(limit=5, days=30, club_id=2)

    assert drops[0]["headline"] == "Дмитрий из WALLZ"
    assert "AND o.club_id = %s" in cursor.query
    assert cursor.params[-2:] == (2, 5)
