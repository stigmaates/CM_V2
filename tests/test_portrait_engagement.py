import importlib
import json
import sqlite3
from datetime import datetime

from app.services import mission_history
from app.services.missions import _next_club_mission_id
from scripts import rebuild_user_portrait as portrait


class Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?")
        sql = sql.replace(
            "ON DUPLICATE KEY UPDATE completed_at = completed_at",
            "ON CONFLICT (club_id, guest_id, mission_id) DO NOTHING",
        )
        sql = sql.replace(
            "ON DUPLICATE KEY UPDATE completed_at = LEAST(completed_at, VALUES(completed_at))",
            "ON CONFLICT (club_id, guest_id, mission_id) DO UPDATE SET "
            "completed_at = MIN(completed_at, excluded.completed_at)",
        )
        self.result = self.db.execute(sql, params)

    def fetchall(self):
        result = []
        for raw in self.result.fetchall():
            row = dict(raw)
            for key in ("first_completed_at", "last_completed_at", "last_opening_at"):
                if row.get(key):
                    row[key] = datetime.fromisoformat(row[key])
            result.append(row)
        return result

    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row else None


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE clubs (club_id INTEGER, timezone TEXT);
            INSERT INTO clubs VALUES (2, 'Asia/Yekaterinburg'), (3, 'Europe/Moscow');
            CREATE TABLE guest_mission_completions (
                club_id INTEGER, guest_id INTEGER, mission_id TEXT, completed_at TEXT,
                PRIMARY KEY (club_id, guest_id, mission_id));
            CREATE TABLE guest_wheel_token_transactions (
                club_id INTEGER, guest_id INTEGER, source_id TEXT, created_at TEXT,
                source_type TEXT, amount INTEGER);
            CREATE TABLE cm_bonus_transactions (
                club_id INTEGER, guest_id INTEGER, source_id TEXT, created_at TEXT,
                source_type TEXT, amount INTEGER, status TEXT);
            CREATE TABLE club_cases (id INTEGER, club_id INTEGER, name TEXT);
            CREATE TABLE guest_case_openings (club_id INTEGER, guest_id INTEGER, case_id INTEGER, created_at TEXT);
        """)

    def cursor(self):
        return Cursor(self.db)


def test_case_breakdown_keeps_inactive_or_deleted_cases_and_separates_clubs():
    conn = Connection()
    conn.db.executescript("""
        INSERT INTO club_cases VALUES (1, 2, 'CS2'), (1, 3, 'Other club');
        INSERT INTO guest_case_openings VALUES
          (2, 42, 1, '2026-09-01 12:00:00'), (2, 42, 1, '2026-09-02 12:00:00'),
          (2, 42, 9, '2026-09-03 12:00:00'), (3, 42, 1, '2026-09-01 12:00:00');
    """)
    rows = portrait.fetch_cases_agg(conn)
    assert rows[(2, 42)]["case_openings_count"] == 3
    assert rows[(3, 42)]["case_openings_count"] == 1
    cases = rows[(2, 42)]["case_openings_by_case"]
    assert [(item["case_id"], item["openings_count"]) for item in cases] == [(1, 2), (9, 1)]
    assert cases[0]["name"] == "CS2"
    assert "удалён" in cases[1]["name"]
    assert cases[1]["last_opening_at"] == "2026-09-03T12:00:00+00:00"


def test_missions_monthly_average_includes_empty_months_and_club_local_month_boundary():
    conn = Connection()
    conn.db.executescript("""
        INSERT INTO guest_mission_completions VALUES
          (2, 42, '1', '2026-06-30 21:00:00'),
          (2, 42, '2', '2026-09-01 12:00:00'),
          (3, 42, '1', '2026-09-01 12:00:00');
    """)
    rows = portrait.fetch_missions_agg(conn, datetime(2026, 9, 10))
    assert rows[(2, 42)]["missions_completed_count"] == 2
    # In Ufa the first event is July 1: July, August (zero), September.
    assert rows[(2, 42)]["avg_missions_per_month"] == 0.67
    assert rows[(3, 42)]["avg_missions_per_month"] == 1
    assert rows[(2, 42)]["last_mission_activity_date"] == datetime(2026, 9, 1, 12)


def test_reward_backfill_counts_two_currencies_once_without_mission_definitions():
    conn = Connection()
    conn.db.executescript("""
        INSERT INTO guest_wheel_token_transactions VALUES
          (2, 42, '11', '2026-07-01 10:00:00', 'mission', 1),
          (2, 42, '12', '2026-07-02 10:00:00', 'mission', 1),
          (2, 42, '13', '2026-07-02 10:00:00', 'manual', 1);
        INSERT INTO cm_bonus_transactions VALUES
          (2, 42, '11', '2026-07-01 10:01:00', 'mission', 100, 'done'),
          (2, 42, '14', '2026-07-02 10:00:00', 'mission', 100, 'failed');
    """)
    migration = importlib.import_module("migrations.versions.0026_portrait_engagement")

    class BackfillCursor(Cursor):
        def execute(self, sql, params=()):
            if "INSERT INTO guest_mission_completions" in sql:
                super().execute(sql, params)

        def fetchone(self):
            return {"cnt": 1}

    for _ in range(2):
        migration.upgrade(BackfillCursor(conn.db))
    # Re-observing an already rewarded mission must retain its historical date.
    mission_history.record_mission_completion(conn.cursor(), 2, 42, 11)
    rows = portrait.fetch_missions_agg(conn, datetime(2026, 9, 10))
    assert rows[(2, 42)]["missions_completed_count"] == 2
    assert rows[(2, 42)]["avg_missions_per_month"] == 0.67


def test_completion_without_reward_is_persisted_once():
    conn = Connection()
    for _ in range(2):
        mission_history.record_mission_completion(conn.cursor(), 2, 42, 77)
    assert conn.db.execute("SELECT COUNT(*) FROM guest_mission_completions").fetchone()[0] == 1


def test_new_mission_does_not_reuse_deleted_completed_mission_id():
    conn = Connection()
    conn.db.executescript("""
        CREATE TABLE club_missions (id INTEGER);
        INSERT INTO club_missions VALUES (5);
        INSERT INTO guest_mission_completions VALUES (2, 42, '10', '2026-07-01 12:00:00');
    """)
    assert _next_club_mission_id(conn.cursor()) == 11


def test_build_records_populates_engagement_and_empty_defaults(monkeypatch):
    monkeypatch.setattr(portrait, "fetch_guests", lambda conn: {(2, 42): {}, (2, 43): {}})
    monkeypatch.setattr(portrait, "fetch_sessions_agg", lambda *args: {})
    monkeypatch.setattr(portrait, "fetch_topups_agg", lambda *args: {})
    monkeypatch.setattr(portrait, "fetch_spins_agg", lambda *args: {})
    monkeypatch.setattr(portrait, "fetch_steam_games_agg", lambda *args: {})
    monkeypatch.setattr(
        portrait,
        "fetch_cases_agg",
        lambda conn: {
            (2, 42): {"case_openings_count": 2, "case_openings_by_case": [{"case_id": 1, "openings_count": 2}]}
        },
    )
    monkeypatch.setattr(
        portrait,
        "fetch_missions_agg",
        lambda *args: {(2, 42): {"missions_completed_count": 3, "avg_missions_per_month": 1.5}},
    )
    active, empty = portrait.build_records(None)
    assert active["missions_completed_count"] == 3
    assert active["avg_missions_per_month"] == 1.5
    assert json.loads(active["case_openings_by_case"])[0]["openings_count"] == 2
    assert empty["missions_completed_count"] == empty["case_openings_count"] == 0
    assert empty["avg_missions_per_month"] == 0
    assert json.loads(empty["case_openings_by_case"]) == []
