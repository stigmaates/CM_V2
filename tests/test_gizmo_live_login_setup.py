"""Stage-only live fixture refuses unrelated identities and cleans up on failure."""

import pytest

from app.integrations.gizmo_sync import atomic_json
from scripts import prepare_gizmo_stage_login as setup
from tests.test_gizmo_guest_features import GuestConnection
from tests.test_guest_service_pause import AuthCursor


@pytest.fixture
def ready(tmp_path, monkeypatch):
    conn = GuestConnection()
    conn.statements = []
    monkeypatch.setattr(conn, "cursor", lambda: AuthCursor(conn))
    conn.db.executescript("""
        ALTER TABLE clubs ADD COLUMN name TEXT;
        ALTER TABLE clubs ADD COLUMN owner_id INT;
        CREATE TABLE guest_login_tokens(token TEXT,club_id INT,guest_id INT,telegram_id INT,is_confirmed INT,expires_at TEXT);
    """)
    conn.db.execute("INSERT INTO clubs VALUES (900002,'gizmo',0,1,?,NULL)", (setup.TEST_NAME,))
    conn.commit()
    atomic_json(tmp_path / "acceptance-900001.json", {"test_club_id": setup.CLUB})
    atomic_json(tmp_path / "sync-900002.json", {"enabled": False, "connection": {"host": "test"}})
    monkeypatch.setattr(setup, "require_stage_environment", lambda: None)
    monkeypatch.setattr(setup, "get_db_connection", lambda: conn)
    monkeypatch.setattr(setup, "verify_bot", lambda: None)
    monkeypatch.setattr(setup, "ensure_guest_login_tokens_club_column", lambda cur: None)
    monkeypatch.setattr(setup, "queue_setup", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "synchronize", lambda *args, **kwargs: {"status": "complete"})

    def service(db, cid, enabled, **kwargs):
        assert cid == setup.CLUB
        db.db.execute("UPDATE clubs SET service_enabled=? WHERE club_id=?", (enabled, cid))
        db.commit()

    monkeypatch.setattr(setup, "set_service", service)
    monkeypatch.setattr(setup, "pause_sync", lambda *args, **kwargs: None)
    yield conn, tmp_path
    conn.db.close()


def test_prepare_and_finish_preserve_source_and_revoke_login(ready):
    conn, directory = ready
    before = conn.records("clubs")[0]
    report = setup.run("prepare", directory=directory)
    assert report["status"] == "ready_for_browser"
    assert conn.records("guests")[0]["telegram_id"] == setup.RECIPIENT
    conn.db.execute("INSERT INTO guest_login_tokens VALUES ('test',900002,900900002,328908187,1,'2099-01-01')")
    conn.commit()
    report = setup.run("finish", directory=directory)
    assert report["confirmed_bot_logins"] == 1
    assert conn.records("guests")[0]["telegram_id"] is None
    assert conn.records("guest_login_tokens")[0]["is_confirmed"] == 0
    assert conn.records("clubs")[0] == before
    assert conn.records("clubs")[1]["service_enabled"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE clubs SET owner_id=1 WHERE club_id=900002",
        "UPDATE clubs SET name='Real club' WHERE club_id=900002",
        "UPDATE clubs SET integration_provider='langame' WHERE club_id=900002",
        "INSERT INTO guests(club_id,guest_id,fio,telegram_id) VALUES(900002,10,'Real guest',123)",
        "INSERT INTO guests(club_id,guest_id,fio) VALUES(900002,900900002,'Real guest')",
    ],
)
def test_unrelated_targets_refused_before_network(ready, monkeypatch, mutation):
    conn, directory = ready
    conn.db.execute(mutation)
    conn.commit()

    def forbidden():
        pytest.fail("Telegram contacted before isolation checks")

    monkeypatch.setattr(setup, "verify_bot", forbidden)
    with pytest.raises(ValueError):
        setup.run("prepare", directory=directory)
    assert conn.records("clubs")[1]["service_enabled"] == 0


def test_sync_failure_leaves_test_disabled(ready, monkeypatch):
    conn, directory = ready
    monkeypatch.setattr(setup, "synchronize", lambda *args, **kwargs: {"status": "error"})
    with pytest.raises(ValueError, match="не обновилась"):
        setup.run("prepare", directory=directory)
    assert conn.records("clubs")[1]["service_enabled"] == 0
    assert not conn.records("guests")


def test_repeat_does_not_interrupt_live_test(ready):
    conn, directory = ready
    setup.run("prepare", directory=directory)
    with pytest.raises(ValueError, match="уже подготовлен"):
        setup.run("prepare", directory=directory)
    assert conn.records("clubs")[1]["service_enabled"] == 1
