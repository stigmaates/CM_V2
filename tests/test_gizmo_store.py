"""Exercise idempotency and rollback against real SQLite transactions.

Only SQL dialect and the MySQL advisory lock are translated here.
"""

import copy
import re
import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from app.integrations.gizmo_import import save


class Cursor:
    def __init__(self, owner):
        self.owner = owner
        self.cur = owner.db.cursor()
        self.special = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cur.close()

    def execute(self, sql, params=()):
        self.special = None
        if "GET_LOCK" in sql:
            self.special = {"acquired": 1}
            return
        if "RELEASE_LOCK" in sql:
            return
        if self.owner.fail and "INSERT INTO guest_sessions" in sql:
            raise RuntimeError("injected write failure")
        sql = sql.replace(" FOR UPDATE", "").replace("%s", "?")
        sql = sql.replace("ON DUPLICATE KEY UPDATE", "ON CONFLICT DO UPDATE SET")
        sql = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", sql)
        params = tuple(str(x) if isinstance(x, Decimal) else x for x in params)
        self.cur.execute(sql, params)

    def fetchall(self):
        return [dict(row) for row in self.cur.fetchall()]

    def executemany(self, sql, values):
        self.owner.batches.append((sql, len(values)))
        for params in values:
            self.execute(sql, params)

    def fetchone(self):
        if self.special:
            return self.special
        row = self.cur.fetchone()
        return dict(row) if row else None


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.fail = False
        self.batches = []
        self.db.executescript("""
            CREATE TABLE clubs (club_id INTEGER PRIMARY KEY,integration_provider TEXT,service_enabled INTEGER,integration_ready INTEGER);
            INSERT INTO clubs VALUES (900001,'gizmo',0,0);
            CREATE TABLE club_integrations (club_id INTEGER PRIMARY KEY,external_branch_id TEXT,settings TEXT,last_import_at TEXT);
            INSERT INTO club_integrations (club_id) VALUES (900001);
            CREATE TABLE guests (club_id INTEGER,guest_id INTEGER,phone TEXT,fio TEXT,birth_date TEXT,date_insert TEXT,
                created_at TEXT,gender TEXT,telegram_id INTEGER,PRIMARY KEY(club_id,guest_id));
            CREATE TABLE club_pc_names (id INTEGER PRIMARY KEY,club_id INTEGER,uuid TEXT,display_name TEXT,sort_order INTEGER,is_archived INTEGER NOT NULL DEFAULT 0,UNIQUE(club_id,uuid));
            CREATE TABLE guest_sessions (club_id INTEGER,id INTEGER,guest_id INTEGER,uuid TEXT,date_start TEXT,date_stop TEXT,source_guest_id INTEGER,PRIMARY KEY(club_id,id));
            CREATE TABLE guest_balance_topups (id INTEGER PRIMARY KEY,club_id INTEGER,topup_id INTEGER,guest_id INTEGER,amount NUMERIC,
                topup_at TEXT,created_at TEXT,updated_at TEXT,source_guest_id INTEGER,UNIQUE(club_id,topup_id));
            CREATE TABLE guest_pulse_dirty (club_id INTEGER PRIMARY KEY,generation INTEGER);
        """)

    def cursor(self):
        return Cursor(self)

    def rollback(self):
        self.db.rollback()

    def begin(self):
        self.db.execute("BEGIN")

    def commit(self):
        self.db.commit()

    def records(self, table):
        return [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")]


@pytest.fixture
def sample():
    return {
        "scope": {"branch_id": 1, "session_source": "sessions+usersessions", "source": {"address": "test"}},
        "guests": [
            dict(
                guest_id=10,
                phone="79001112233",
                fio="Иван",
                birth_date=None,
                date_insert=datetime(2026, 1, 1),
                gender=None,
            )
        ],
        "hosts": [dict(uuid="gizmo:5", display_name="PC05", sort_order=5)],
        "sessions": [
            dict(
                id=123,
                guest_id=10,
                uuid="gizmo:5",
                date_start=datetime(2026, 10, 1, 10),
                date_stop=datetime(2026, 10, 1, 11),
            )
        ],
        "topups": [dict(topup_id=50, guest_id=10, amount=Decimal("120.00"), topup_at=datetime(2026, 10, 1, 10))],
    }


def test_repeat_import_preserves_telegram_and_manual_pc_names_without_duplicate_topups(sample):
    conn = Connection()
    save(conn, 900001, sample)
    conn.db.execute("UPDATE guests SET telegram_id=777")
    conn.db.execute("UPDATE club_pc_names SET display_name='VIP',sort_order=1")
    conn.commit()
    save(conn, 900001, sample)
    assert (
        len(conn.records("guests"))
        == len(conn.records("guest_sessions"))
        == len(conn.records("guest_balance_topups"))
        == 1
    )
    assert conn.records("guests")[0]["telegram_id"] == 777
    assert conn.records("club_pc_names")[0]["display_name"] == "VIP"
    assert conn.records("club_pc_names")[0]["sort_order"] == 1
    assert conn.records("guest_balance_topups")[0]["id"] == -1
    assert conn.records("club_pc_names")[0]["id"] == -1


def test_failure_rolls_back_guests_equipment_and_import_state(sample):
    conn = Connection()
    conn.fail = True
    with pytest.raises(RuntimeError, match="injected"):
        save(conn, 900001, sample)
    assert all(
        not conn.records(table)
        for table in ("guests", "club_pc_names", "guest_sessions", "guest_balance_topups", "guest_pulse_dirty")
    )
    assert conn.records("club_integrations")[0]["last_import_at"] is None


def test_cancellation_reconciles_existing_topup_instead_of_leaving_previous_revenue(sample):
    conn = Connection()
    save(conn, 900001, sample)
    cancelled = copy.deepcopy(sample)
    cancelled["topups"][0]["amount"] = Decimal("0.00")
    save(conn, 900001, cancelled)
    rows = conn.records("guest_balance_topups")
    assert len(rows) == 1 and rows[0]["amount"] == 0 and rows[0]["id"] == -1


def test_changing_source_or_branch_cannot_overwrite_guest_identity(sample):
    conn = Connection()
    save(conn, 900001, sample)
    changed = copy.deepcopy(sample)
    changed["scope"]["branch_id"] = 2
    with pytest.raises(ValueError, match="branch"):
        save(conn, 900001, changed)
    changed["scope"]["branch_id"] = 1
    changed["scope"]["source"]["address"] = "another"
    with pytest.raises(ValueError, match="identity"):
        save(conn, 900001, changed)


def test_rejected_session_removes_only_same_club_record_atomically(sample):
    conn = Connection()
    save(conn, 900001, sample)
    conn.db.execute(
        "INSERT INTO guest_sessions (club_id,id,guest_id,uuid,date_start,date_stop) VALUES (900002,123,10,'gizmo:5','2026-10-01 10:00:00','2026-10-01 11:00:00')"
    )
    conn.commit()
    corrected = copy.deepcopy(sample)
    corrected["rejected_sessions"] = [dict(id=123, reason="end_before_start")]
    corrected["sessions"] = []
    save(conn, 900001, corrected)
    assert [(r["club_id"], r["id"]) for r in conn.records("guest_sessions")] == [(900002, 123)]


def test_rejected_session_deletion_rolls_back_if_valid_session_write_fails(sample):
    conn = Connection()
    save(conn, 900001, sample)
    corrected = copy.deepcopy(sample)
    corrected["rejected_sessions"] = [dict(id=123, reason="end_before_start")]
    corrected["sessions"][0]["id"] = 124
    conn.fail = True
    with pytest.raises(RuntimeError, match="injected"):
        save(conn, 900001, corrected)
    assert [r["id"] for r in conn.records("guest_sessions")] == [123]


def test_large_import_batches_rows_and_preserves_ids_on_repeat(sample, caplog):
    import logging

    from pymysql.cursors import RE_INSERT_VALUES

    conn = Connection()
    sample["sessions"] = [dict(sample["sessions"][0], id=i) for i in range(1, 1202)]
    sample["topups"] = [dict(sample["topups"][0], topup_id=i) for i in range(1, 1202)]
    with caplog.at_level(logging.INFO, logger="app.integrations.gizmo_import"):
        save(conn, 900001, sample)
    assert len(conn.records("guest_sessions")) == 1201
    topup_ids = {r["topup_id"]: r["id"] for r in conn.records("guest_balance_topups")}
    assert len(topup_ids) == 1201 and max(topup_ids.values()) < 0
    assert [n for sql, n in conn.batches if "INSERT INTO guest_sessions" in sql] == [500, 500, 201]
    assert all(RE_INSERT_VALUES.match(sql) for sql, _ in conn.batches)
    assert "1201/1201" in caplog.text
    assert sample["guests"][0]["phone"] not in caplog.text
    save(conn, 900001, sample)
    assert {r["topup_id"]: r["id"] for r in conn.records("guest_balance_topups")} == topup_ids


def test_archiving_and_restoring_pc_preserves_history_and_manual_name(sample):
    conn = Connection()
    save(conn, 900001, sample)
    conn.db.execute("UPDATE club_pc_names SET display_name='VIP',sort_order=1")
    conn.commit()
    sample["hosts"][0]["deleted"] = True
    save(conn, 900001, sample)
    assert conn.records("club_pc_names")[0]["is_archived"] == 1
    assert len(conn.records("guest_sessions")) == 1
    sample["hosts"][0]["deleted"] = False
    save(conn, 900001, sample)
    pc = conn.records("club_pc_names")[0]
    assert pc["is_archived"] == 0
    assert pc["display_name"] == "VIP" and pc["sort_order"] == 1
    assert len(conn.records("guest_sessions")) == 1


def test_shared_events_keep_source_identity_but_never_create_a_crm_guest(sample):
    conn = Connection()
    sample["guests"] = []
    for row in sample["sessions"] + sample["topups"]:
        row["source_guest_id"] = row["guest_id"]
        row["guest_id"] = None
    save(conn, 900001, sample)
    save(conn, 900001, sample)
    assert conn.records("guests") == []
    assert len(conn.records("guest_sessions")) == len(conn.records("guest_balance_topups")) == 1
    for table in ("guest_sessions", "guest_balance_topups"):
        row = conn.records(table)[0]
        assert row["source_guest_id"] == 10 and row["guest_id"] is None
    sample["topups"][0]["amount"] = Decimal("0.00")
    save(conn, 900001, sample)
    assert conn.records("guest_balance_topups")[0]["amount"] == 0


def test_archived_pc_is_hidden_in_settings_but_visible_in_its_historical_heatmap(sample, monkeypatch):
    from app.services import pc_heatmap

    conn = Connection()
    sample["hosts"][0]["deleted"] = True
    save(conn, 900001, sample)
    original_cursor = conn.cursor

    def reader():
        cursor = original_cursor()
        original_fetch = cursor.fetchall

        def fetch():
            rows = original_fetch()
            for row in rows:
                for field in ("date_start", "date_stop"):
                    if row.get(field):
                        row[field] = datetime.fromisoformat(row[field])
            return rows

        cursor.fetchall = fetch
        return cursor

    conn.cursor = reader
    conn.close = lambda: None
    monkeypatch.setattr(pc_heatmap, "get_db_connection", lambda: conn)
    monkeypatch.setattr(pc_heatmap, "stage_mirror_enabled", lambda: True)
    assert pc_heatmap.get_pc_name_settings(900001) == []
    historical = pc_heatmap.get_pc_hours_heatmap_stats(
        900001, current_start=datetime(2026, 10, 1), current_end=datetime(2026, 10, 2)
    )
    assert historical["total_sessions"] == 1
    assert historical["pcs"][0]["is_archived"] is True
    assert historical["pcs"][0]["name"] == "PC05 (архив)"
    later = pc_heatmap.get_pc_hours_heatmap_stats(
        900001, current_start=datetime(2026, 10, 2), current_end=datetime(2026, 10, 3)
    )
    assert later["pcs"] == []
