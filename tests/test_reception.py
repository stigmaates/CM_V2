from app.main import app
from app.services.reception import _phone_variants, _source_label


def test_reception_role_is_redirected_back_to_reception_from_owner_page():
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 11
        session["role"] = "reception"
        session["club_id"] = 1

    response = client.get("/owner/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/reception/")


def test_reception_phone_variants_cover_common_russian_formats():
    variants = _phone_variants("+7 (987) 153-68-67")

    assert "79871536867" in variants
    assert "89871536867" in variants
    assert "9871536867" in variants


def test_reception_phone_variants_match_local_number_from_leading_eight():
    variants = _phone_variants("89270086145")

    assert "89270086145" in variants
    assert "79270086145" in variants
    assert "9270086145" in variants


def test_reception_labels_topup_reward_in_russian():
    assert _source_label("topup_reward") == "Бонус за пополнение"


def test_reception_loads_old_prizes_scoped_to_guest_and_club(monkeypatch):
    from app.services import reception

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            self.sql = sql
            if "FROM guest_prize_claims" in sql:
                assert "WHERE club_id = %s AND guest_id = %s" in sql
                assert params == (3, 65271)
                assert "LIMIT" not in sql
                assert "created_at >" not in sql

        def fetchone(self):
            return None

        def fetchall(self):
            if "FROM guest_prize_claims" in self.sql:
                return [
                    {"id": 42, "prize_name": "Стикер", "status": "notified",
                     "created_at": "2026-09-30 18:58:37"},
                    {"id": 43, "prize_name": "Стикер", "status": "issued",
                     "created_at": "2026-09-30 18:59:33"},
                ]
            return []

    class Connection:
        closed = False

        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    conn = Connection()
    monkeypatch.setattr(reception, "get_db_connection", lambda: conn)
    monkeypatch.setattr(reception, "_fetch_guest", lambda *a, **kw: {"guest_id": 65271})
    result = reception.get_reception_guest_lookup(club_id=3, phone="test", limit=1)
    assert [p["id"] for p in result["prize_claims"]] == [42, 43]
    assert [p["status_label"] for p in result["prize_claims"]] == ["ожидает выдачи", "выдан"]
    assert conn.closed


def test_reception_template_displays_prizes_and_escapes_their_names():
    from flask import render_template

    lookup = {
        "found": True,
        "guest": {"guest_id": 65271, "bonus_balance": 0, "token_balance": 2},
        "bonus_transactions": [], "token_transactions": [], "redeem_requests": [],
        "prize_claims": [
            {"id": 42, "prize_name": "Стикер <script>alert(1)</script>",
             "status_label": "ожидает выдачи", "created_at": "2026-09-30 18:58:37"},
            {"id": 43, "prize_name": "Стикер", "status_label": "выдан",
             "created_at": "2026-09-30 18:59:33", "issued_at": "2026-10-01 09:00:00"},
        ],
    }
    with app.test_request_context("/reception/"):
        html = render_template("reception/dashboard.html", lookup=lookup, phone="", csrf_token=lambda: "test")
    assert "Призы и выдача" in html
    assert "Заявка №42 · ожидает выдачи" in html
    assert "Заявка №43 · выдан" in html
    assert "выдан: 2026-10-01 09:00:00" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
