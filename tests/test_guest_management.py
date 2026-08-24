import pytest

from app.services import guest_management


class _Cursor:
    def __init__(self, guest_exists=True):
        self.guest_exists = guest_exists
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return {"guest_id": 10} if self.guest_exists else None


class _Connection:
    def __init__(self, guest_exists=True):
        self.cursor_obj = _Cursor(guest_exists)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_adjust_guest_tokens_uses_club_scoped_ledger(monkeypatch):
    conn = _Connection()
    captured = {}
    monkeypatch.setattr(guest_management, "get_db_connection", lambda: conn)

    def add_tokens(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(guest_management, "add_guest_token_transaction", add_tokens)

    result = guest_management.adjust_guest_balance(
        club_id=2,
        guest_id=10,
        balance_type="tokens",
        amount=3,
        actor_user_id=7,
        reason="Компенсация",
    )

    assert result["amount"] == 3
    assert captured["club_id"] == 2
    assert captured["guest_id"] == 10
    assert captured["source_type"] == "owner_manual"
    assert conn.committed is True
    assert conn.closed is True


def test_adjust_guest_balance_rejects_guest_from_another_club(monkeypatch):
    conn = _Connection(guest_exists=False)
    monkeypatch.setattr(guest_management, "get_db_connection", lambda: conn)

    with pytest.raises(ValueError, match="текущем клубе"):
        guest_management.adjust_guest_balance(
            club_id=2,
            guest_id=10,
            balance_type="cm_bonus",
            amount=100,
            actor_user_id=7,
        )

    assert conn.rolled_back is True
    assert conn.committed is False


def test_guest_ban_is_written_with_composite_identity(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(guest_management, "get_db_connection", lambda: conn)

    result = guest_management.set_guest_module_ban(
        club_id=3,
        guest_id=10,
        is_banned=True,
        actor_user_id=7,
        reason="Нарушение правил",
    )

    insert_params = conn.cursor_obj.queries[-1][1]
    assert insert_params[:2] == (3, 10)
    assert result == {"is_banned": True, "reason": "Нарушение правил"}
    assert conn.committed is True
