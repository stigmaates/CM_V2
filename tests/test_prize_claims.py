from app.services import prize_claims


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
    assert insert_params[4] == "[ТЕСТ] Футболка"
    assert "Тестовая заявка из админского режима" in insert_params[5]
    assert "Размер уточнить" in insert_params[5]
