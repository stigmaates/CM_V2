import pytest


@pytest.fixture
def staff_login(monkeypatch):
    """Create a valid synthetic staff login and mock only its account lookup."""
    from app.services import staff_sessions

    accounts = {}
    monkeypatch.setattr(staff_sessions, "load_staff_user", lambda user_id: accounts.get(user_id))

    def login(client, **fields):
        user = dict(user_id=10, role="owner", club_id=7, pass_hash="synthetic-hash", name="Test", login="test")
        user.update(fields)
        accounts[user["user_id"]] = user
        with client.application.app_context():
            stamp = staff_sessions.authority_stamp(user)
        import time

        with client.session_transaction() as session:
            session.update({k: v for k, v in user.items() if k != "pass_hash"})
            session["_staff_authority"] = stamp
            session["_staff_login_at"] = time.time()
        return user

    return login
