"""A mailing pauses between recipients and resumes without resending successes."""

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from scripts import process_mailings as worker


class Cursor:
    def __init__(self, conn):
        self.cursor = conn.db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, args=()):
        self.cursor.execute(sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP"), args)

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self.cursor.fetchall()]


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE clubs(club_id INTEGER,service_enabled INTEGER);
            INSERT INTO clubs VALUES(1,1);
            CREATE TABLE mailings(id INTEGER,club_id INTEGER,status TEXT,message_text TEXT,parse_mode TEXT,
              started_at TEXT,finished_at TEXT,success_count INTEGER,failed_count INTEGER);
            INSERT INTO mailings VALUES(1,1,'queued','test','HTML',NULL,NULL,0,0);
            CREATE TABLE mailing_recipients(id INTEGER,mailing_id INTEGER,guest_id INTEGER,telegram_id INTEGER,
              message_text TEXT,status TEXT,sent_at TEXT,error_text TEXT);
            INSERT INTO mailing_recipients VALUES(1,1,1,1,'test','pending',NULL,NULL),(2,1,2,2,'test','pending',NULL,NULL);
            CREATE TABLE mailing_attachments(id INTEGER,mailing_id INTEGER,file_type TEXT,file_path TEXT,original_name TEXT);
        """)

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.db.commit()


def test_disable_pauses_remaining_recipients_and_resume_does_not_duplicate(monkeypatch):
    from app.services import outbound_policy

    conn = Connection()
    monkeypatch.setattr(outbound_policy, "ensure_outbound_allowed", lambda: None)
    monkeypatch.setattr(worker, "table_has_column", lambda *a: True)
    monkeypatch.setattr(worker, "start_job_run", lambda *a, **kw: 1)
    monkeypatch.setattr(worker, "finish_job_run", lambda *a, **kw: None)
    monkeypatch.setattr(worker.time, "sleep", lambda *a: None)

    @contextmanager
    def lock(*a, **kw):
        yield SimpleNamespace(acquired=True)

    monkeypatch.setattr(worker, "job_lock", lock)
    sent = []

    def send(**kw):
        sent.append(kw["telegram_id"])
        conn.db.execute("UPDATE clubs SET service_enabled=0")
        conn.commit()
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(worker, "send_single_message", send)
    worker.process_one_mailing(conn, 1)
    assert sent == [1]
    assert conn.db.execute("SELECT status FROM mailings").fetchone()[0] == "queued"
    assert [r[0] for r in conn.db.execute("SELECT status FROM mailing_recipients ORDER BY id")] == ["sent", "pending"]
    worker.process_one_mailing(conn, 1)
    assert sent == [1]
    conn.db.execute("UPDATE clubs SET service_enabled=1")
    conn.commit()
    worker.process_one_mailing(conn, 1)
    assert sent == [1, 2]
    assert tuple(conn.db.execute("SELECT status,success_count FROM mailings").fetchone()) == ("completed", 2)
