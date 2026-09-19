from datetime import datetime

from app.services import prize_claims, wheel


class _Cursor:
    def __init__(self):
        self.queries = []
        self.lastrowid = 777

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return None


def test_create_prize_claim_marks_test_claim(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(prize_claims, "ensure_prize_claim_tables", lambda cur: None)

    claim_id = prize_claims.create_prize_claim(
        cursor,
        guest_id=900000001,
        club_id=1,
        spin_id=-123,
        prize={
            "id": 5,
            "name": "Футболка",
            "description": "Размер уточнить",
            "image_url": "/uploads/cases/1/items/prize.webp",
            "bonus_amount": 0,
        },
        test_mode=True,
    )

    assert claim_id == 777
    insert_params = cursor.queries[0][1]
    assert insert_params[3] == "case_opening"
    assert insert_params[4] == "123"
    assert insert_params[6] == "[ТЕСТ] Футболка"
    assert "Тестовая заявка из админского режима" in insert_params[7]
    assert "Размер уточнить" in insert_params[7]


class _SyncCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _SyncConnection:
    def __init__(self):
        self.cursor_obj = _SyncCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_completed_mission_with_text_reward_creates_and_notifies_claim(monkeypatch):
    conn = _SyncConnection()
    created = []
    notified = []
    mission = {
        "id": 17,
        "name": "Пять визитов",
        "reward_text": "Бесплатный напиток",
        "token_reward": 0,
        "cm_bonus_reward": 0,
        "is_completed": True,
    }

    monkeypatch.setattr(wheel, "get_wheel_settings", lambda _club_id: None)
    monkeypatch.setattr(wheel, "get_guest_missions_with_progress", lambda *_args: [mission])
    monkeypatch.setattr(wheel, "get_db_connection", lambda: conn)
    monkeypatch.setattr(wheel, "ensure_token_tables", lambda _cursor: None)
    monkeypatch.setattr(wheel, "ensure_cm_bonus_tables", lambda _cursor: None)
    monkeypatch.setattr(wheel, "record_mission_completion", lambda *_args: True)
    monkeypatch.setattr(
        wheel,
        "create_prize_claim",
        lambda **kwargs: created.append(kwargs) or 91,
    )
    monkeypatch.setattr(wheel, "notify_prize_claim_admin_chat", lambda claim_id: notified.append(claim_id))

    result = wheel.sync_guest_wheel_tokens(guest_id=42, club_id=2)

    assert result == [mission]
    assert conn.committed is True
    assert conn.closed is True
    assert created[0]["spin_id"] is None
    assert created[0]["source_type"] == "mission"
    assert created[0]["source_id"] == "17"
    assert created[0]["prize"]["name"] == "Бесплатный напиток"
    assert "Пять визитов" in created[0]["prize"]["description"]
    assert notified == [91]


def test_existing_mission_completion_does_not_create_duplicate_claim(monkeypatch):
    conn = _SyncConnection()
    created = []
    mission = {
        "id": 17,
        "name": "Пять визитов",
        "reward_text": "Бесплатный напиток",
        "token_reward": 0,
        "cm_bonus_reward": 0,
        "is_completed": True,
    }

    monkeypatch.setattr(wheel, "get_wheel_settings", lambda _club_id: None)
    monkeypatch.setattr(wheel, "get_guest_missions_with_progress", lambda *_args: [mission])
    monkeypatch.setattr(wheel, "get_db_connection", lambda: conn)
    monkeypatch.setattr(wheel, "ensure_token_tables", lambda _cursor: None)
    monkeypatch.setattr(wheel, "ensure_cm_bonus_tables", lambda _cursor: None)
    monkeypatch.setattr(wheel, "record_mission_completion", lambda *_args: False)
    monkeypatch.setattr(wheel, "create_prize_claim", lambda **kwargs: created.append(kwargs))
    monkeypatch.setattr(wheel, "notify_prize_claim_admin_chat", lambda _claim_id: None)

    wheel.sync_guest_wheel_tokens(guest_id=42, club_id=2)

    assert created == []


def test_issued_prize_message_uses_club_local_time():
    message = prize_claims.format_prize_claim_message(
        {
            "id": 17,
            "club_id": 2,
            "guest_id": 42,
            "guest_name": "Иван Иванов",
            "guest_phone": "79990000000",
            "prize_name": "Наушники",
            "status": "issued",
            "issued_by_username": "@admin",
            "issued_at": datetime(2026, 9, 8, 16, 34),
            "club_timezone": "Asia/Yekaterinburg",
        },
        issued=True,
    )

    assert "Дата выдачи (время клуба): <b>08.09.2026 21:34</b>" in message
