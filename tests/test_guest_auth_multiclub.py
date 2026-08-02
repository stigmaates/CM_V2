import app.services.guest_auth as guest_auth
import bot.main as guest_bot


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_guest_login_token_stores_club_id(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(guest_auth, "_guest_login_tokens_club_column_ready", True)
    monkeypatch.setattr(guest_auth, "get_db_connection", lambda: conn)

    token = guest_auth.create_guest_login_token(2)

    assert token
    insert_sql, params = cursor.queries[0]
    assert "club_id" in insert_sql
    assert params[1] == 2
    assert conn.committed
    assert conn.closed


def test_bot_phone_lookup_is_scoped_to_token_club(monkeypatch):
    cursor = FakeCursor(
        rows=[
            {"guest_id": 64103, "club_id": 2, "phone": "9969958440", "fio": "Андриянов Леонид"},
        ]
    )
    monkeypatch.setattr(guest_bot, "get_db_connection", lambda: FakeConnection(cursor))

    guest, matches_count = guest_bot.find_guest_by_phone("89969958440", club_id=2)

    assert matches_count == 1
    assert guest["club_id"] == 2
    lookup_sql, params = cursor.queries[0]
    assert "WHERE club_id = %s" in lookup_sql
    assert params == (2,)
