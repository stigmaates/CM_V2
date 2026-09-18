import importlib
import sqlite3
from datetime import datetime

import pytest
from flask import render_template

from app.main import app
from app.routes.admin import dashboard
from scripts import sync_guests


class Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        if "information_schema.COLUMNS" in sql:
            columns = self.db.execute("PRAGMA table_info(clubs)").fetchall()
            self.result = {"cnt": int(any(row[1] == "cooperation_started_at" for row in columns))}
        else:
            params = tuple(value.isoformat(" ") if isinstance(value, datetime) else value for value in params)
            self.db.execute(sql.replace("%s", "?").replace("LEAST(", "MIN("), params)

    def fetchone(self):
        return self.result


class Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def close(self):
        pass


def test_migration_backfills_only_earliest_successful_guest_initial_and_is_repeatable():
    migration = importlib.import_module("migrations.versions.0025_club_cooperation_started_at")
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE clubs (club_id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO clubs VALUES (?)", [(1,), (2,), (3,)])
        db.execute("CREATE TABLE admin_sync_logs (club_id INT, script_name TEXT, sync_mode TEXT, status TEXT, started_at TEXT)")
        db.executemany("INSERT INTO admin_sync_logs VALUES (?, ?, ?, ?, ?)", [
            (1, "guests", "initial", "success", "2026-09-02 21:30:00"),
            (1, "guests", "initial", "success", "2026-09-01 21:30:00"),
            (1, "guests", "initial", "error", "2026-08-01 00:00:00"),
            (1, "guests", "incremental", "success", "2026-07-01 00:00:00"),
            (1, "sessions", "initial", "success", "2026-06-01 00:00:00"),
            (2, "guests", "initial", "running", "2026-09-01 00:00:00"),
        ])
        migration.upgrade(Cursor(db))
        assert db.execute("SELECT cooperation_started_at FROM clubs ORDER BY club_id").fetchall() == [
            ("2026-09-01 21:30:00",), (None,), (None,),
        ]
        db.execute("UPDATE clubs SET cooperation_started_at = '2026-05-01 00:00:00' WHERE club_id = 1")
        migration.upgrade(Cursor(db))
        assert db.execute("SELECT cooperation_started_at FROM clubs WHERE club_id = 1").fetchone()[0] == "2026-05-01 00:00:00"


def test_record_keeps_first_date_and_handles_overlapping_runs(monkeypatch):
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE clubs (club_id INT PRIMARY KEY, cooperation_started_at TEXT)")
        db.executemany("INSERT INTO clubs VALUES (?, NULL)", [(1,), (2,)])
        monkeypatch.setattr(sync_guests, "get_db_connection", lambda: Connection(db))
        for day in (2, 3, 1, 4):
            sync_guests.record_cooperation_start(1, datetime(2026, 9, day))
        assert db.execute("SELECT cooperation_started_at FROM clubs ORDER BY club_id").fetchall() == [
            ("2026-09-01 00:00:00",), (None,),
        ]


@pytest.mark.parametrize("failure", [None, "fetch", "save", "disabled"])
def test_initial_sync_records_date_only_after_successful_save(monkeypatch, failure):
    events = []
    monkeypatch.setattr(sync_guests, "get_club_data", lambda club_id: {
        "club_id": club_id, "service_enabled": failure != "disabled", "secret": "test", "lg_api_key": "test",
    })

    def step(name):
        events.append(name)
        if failure == name:
            raise RuntimeError("Test failure")

    def record(club_id, started_at):
        assert club_id == 1
        assert isinstance(started_at, datetime)
        events.append("record")

    monkeypatch.setattr(sync_guests, "fetch_guests", lambda *args, **kwargs: step("fetch") or [])
    monkeypatch.setattr(sync_guests, "save_guests", lambda *args: step("save"))
    monkeypatch.setattr(sync_guests, "record_cooperation_start", record)
    if failure in {"fetch", "save"}:
        with pytest.raises(RuntimeError):
            sync_guests.sync_guests(1)
        assert "record" not in events
    else:
        sync_guests.sync_guests(1)
        assert events == ([] if failure == "disabled" else ["fetch", "save", "record"])


def test_admin_date_uses_club_timezone_and_renders_sortable_column(monkeypatch):
    rows = [
        {"club_id": 1, "cooperation_started_at": datetime(2026, 9, 1, 20, 30), "timezone": "Asia/Yekaterinburg"},
        {"club_id": 2, "cooperation_started_at": None, "timezone": "Europe/Moscow"},
    ]

    class QueryCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            assert "c.cooperation_started_at" in sql

        def fetchall(self):
            return rows

        def cursor(self):
            return self

    monkeypatch.setattr(dashboard, "table_has_column", lambda *args: True)
    monkeypatch.setattr(dashboard, "get_db_connection", QueryCursor)
    clubs = dashboard.get_clubs_for_admin()
    assert clubs[0]["cooperation_started_date"] == "02.09.2026"
    assert clubs[0]["cooperation_started_sort"] == "2026-09-02"
    assert clubs[1]["cooperation_started_date"] is None
    with app.test_request_context("/admin/clubs"):
        html = render_template("admin/clubs.html", clubs=clubs, active_page="clubs")
        empty_html = render_template("admin/clubs.html", clubs=[], active_page="clubs")
    assert html.index("Обслуживание") < html.index("Начало сотрудничества")
    assert 'data-sort-value="2026-09-02"' in html
    assert "02.09.2026" in html
    assert "Нет данных об успешной initial-загрузке гостей" in html
    assert 'colspan="8"' in empty_html
