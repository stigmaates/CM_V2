import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app.services import owner_profile


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.executions.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=None):
        self.fake_cursor = FakeCursor(row)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_update_owner_profile_changes_name_without_password(monkeypatch):
    conn = FakeConnection({"user_id": 7, "pass_hash": generate_password_hash("old-password")})
    monkeypatch.setattr(owner_profile, "get_db_connection", lambda: conn)

    result = owner_profile.update_owner_profile(user_id=7, club_id=2, name=" Новое имя ")

    assert result == {"name": "Новое имя", "password_changed": False}
    assert conn.committed is True
    assert conn.closed is True
    update_query, update_params = conn.fake_cursor.executions[-1]
    assert "UPDATE users SET name = %s" in update_query
    assert update_params == ("Новое имя", 7, 2)


def test_update_owner_profile_changes_password(monkeypatch):
    conn = FakeConnection({"user_id": 7, "pass_hash": generate_password_hash("old-password")})
    monkeypatch.setattr(owner_profile, "get_db_connection", lambda: conn)

    result = owner_profile.update_owner_profile(
        user_id=7,
        club_id=2,
        name="Дмитрий",
        current_password="old-password",
        new_password="new-password",
    )

    assert result["password_changed"] is True
    assert conn.committed is True
    update_query, update_params = conn.fake_cursor.executions[-1]
    assert "pass_hash = %s" in update_query
    assert update_params[0] == "Дмитрий"
    assert check_password_hash(update_params[1], "new-password")
    assert update_params[2:] == (7, 2)


def test_update_owner_profile_rejects_wrong_current_password(monkeypatch):
    conn = FakeConnection({"user_id": 7, "pass_hash": generate_password_hash("old-password")})
    monkeypatch.setattr(owner_profile, "get_db_connection", lambda: conn)

    with pytest.raises(ValueError, match="Текущий пароль указан неверно"):
        owner_profile.update_owner_profile(
            user_id=7,
            club_id=2,
            name="Дмитрий",
            current_password="wrong-password",
            new_password="new-password",
        )

    assert conn.committed is False
    assert conn.rolled_back is True
    assert conn.closed is True


def test_update_owner_profile_is_scoped_to_user_and_club(monkeypatch):
    conn = FakeConnection(None)
    monkeypatch.setattr(owner_profile, "get_db_connection", lambda: conn)

    with pytest.raises(ValueError, match="Профиль владельца не найден"):
        owner_profile.update_owner_profile(user_id=7, club_id=999, name="Дмитрий")

    select_query, select_params = conn.fake_cursor.executions[0]
    assert "user_id = %s" in select_query
    assert "club_id = %s" in select_query
    assert select_params == (7, 999)
    assert conn.rolled_back is True
