"""End-to-end storage contract on isolated SQLite; optional native MySQL.

GUEST_PULSE_TEST_SOCKET opts into a dedicated test server; each test creates a
random database. Never reads application DB credentials. SQLite translates SQL
syntax and advisory locks, so it cannot certify MySQL locking/trigger behavior.
"""

import importlib
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from uuid import uuid4

import pymysql
import pytest
from pymysql.cursors import DictCursor

from app.services.guest_pulse import get_current, refresh_club

NOW = datetime(2026, 9, 11, 8)


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        if "information_schema.COLUMNS" in sql:
            columns = {r["name"] for r in self.conn.db.execute("PRAGMA table_info(user_portrait)")}
            self.result = [{"cnt": int(params[0] in columns)}]
            return
        if "information_schema.TRIGGERS" in sql:
            self.result = [
                {"TRIGGER_NAME": r["name"]}
                for r in self.conn.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            ]
            return
        if "GET_LOCK(" in sql:
            self.result = [{"acquired": 1}]
            return
        if "RELEASE_LOCK(" in sql:
            self.result = [{"released": 1}]
            return
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        sql = sql.replace("BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        sql = re.sub(r",\s*KEY \w+ \([^)]*\)", "", sql)
        sql = re.sub(r"UNIQUE KEY \w+", "UNIQUE", sql)
        sql = sql.split(" ENGINE=InnoDB")[0]
        sql = re.sub(r"ON DUPLICATE KEY UPDATE", "ON CONFLICT DO UPDATE SET", sql)
        sql = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", sql)
        if sql.startswith("CREATE TRIGGER"):
            sql = sql.replace("FOR EACH ROW INSERT", "FOR EACH ROW BEGIN INSERT") + "; END"
        if "UPDATE user_portrait up LEFT JOIN" in sql:
            # Equivalent projection, not a MySQL syntax test.
            sql = """UPDATE user_portrait SET
                health_score=(SELECT health_score FROM guest_pulse_current p WHERE p.club_id=user_portrait.club_id AND p.guest_id=user_portrait.guest_id),
                value_score=(SELECT value_score FROM guest_pulse_current p WHERE p.club_id=user_portrait.club_id AND p.guest_id=user_portrait.guest_id)
                WHERE club_id=?"""
        params = tuple(
            p.isoformat(sep=" ") if isinstance(p, datetime) else p.isoformat() if isinstance(p, date) else p
            for p in params
        )
        cursor = self.conn.db.execute(sql, params)
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.lastrowid
        self.result = [dict(r) for r in cursor.fetchall()]
        for r in self.result:
            for key in (
                "calculated_at",
                "created_at",
                "expires_at",
                "backfilled_at",
                "date_start",
                "date_stop",
                "topup_at",
                "at",
                "changed_at",
                "started_at",
                "completed_at",
            ):
                if isinstance(r.get(key), str):
                    r[key] = datetime.fromisoformat(r[key])
            if isinstance(r.get("snapshot_date"), str):
                r["snapshot_date"] = date.fromisoformat(r["snapshot_date"])

    def executemany(self, sql, params):
        for p in params:
            self.execute(sql, p)

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


class Connection:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()


@pytest.fixture
def database(tmp_path):
    socket = os.environ.get("GUEST_PULSE_TEST_SOCKET")
    name = "guest_pulse_test_" + uuid4().hex
    admin = None
    if socket:
        admin = pymysql.connect(unix_socket=socket, user="root", autocommit=True)
        with admin.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{name}`")

    def connect():
        return (
            pymysql.connect(unix_socket=socket, user="root", database=name, cursorclass=DictCursor)
            if socket
            else Connection(tmp_path / "pulse.sqlite")
        )

    def execute(sql, params=()):
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result = cur.fetchall()
            conn.commit()
            return result
        finally:
            conn.close()

    schema = [
        "CREATE TABLE clubs (club_id INT PRIMARY KEY, timezone VARCHAR(64), service_enabled INT)",
        "CREATE TABLE guests (club_id INT,guest_id BIGINT,fio VARCHAR(80),phone VARCHAR(32),telegram_id BIGINT,PRIMARY KEY(club_id,guest_id))",
        "CREATE TABLE guest_sessions (id INT PRIMARY KEY,club_id INT,guest_id BIGINT,date_start DATETIME,date_stop DATETIME)",
        "CREATE TABLE guest_balance_topups (club_id INT,guest_id BIGINT,amount DECIMAL(12,2),topup_at DATETIME)",
        "CREATE TABLE guest_mission_completions (club_id INT,guest_id BIGINT,completed_at DATETIME)",
        "CREATE TABLE guest_wheel_spins (club_id INT,guest_id BIGINT,created_at DATETIME)",
        "CREATE TABLE guest_wheel_token_transactions (club_id INT,guest_id BIGINT,source_type VARCHAR(32),created_at DATETIME)",
        "CREATE TABLE guest_case_openings (club_id INT,guest_id BIGINT,created_at DATETIME)",
        "CREATE TABLE cm_bonus_transactions (club_id INT,guest_id BIGINT,source_type VARCHAR(32),status VARCHAR(32),created_at DATETIME)",
        "CREATE TABLE cm_bonus_redeem_requests (club_id INT,guest_id BIGINT,status VARCHAR(32),processed_at DATETIME)",
        "CREATE TABLE guest_prize_claims (club_id INT,guest_id BIGINT,status VARCHAR(32),issued_at DATETIME)",
        "CREATE TABLE guest_game_contracts (club_id INT,guest_id BIGINT,status VARCHAR(32),started_at DATETIME,completed_at DATETIME)",
        "CREATE TABLE user_portrait (club_id INT,guest_id BIGINT,favorite_game VARCHAR(16),favorite_game_hours DECIMAL(12,1),recent_game_14d VARCHAR(16),recent_game_14d_hours DECIMAL(12,1),steam_game_stats_updated_at DATETIME,PRIMARY KEY(club_id,guest_id))",
        "INSERT INTO clubs VALUES (2,'Asia/Yekaterinburg',1),(3,'Europe/Moscow',1)",
        "INSERT INTO guests VALUES (2,42,'Тест',NULL,100),(3,42,'Другой клуб',NULL,NULL),(2,43,'Без визитов',NULL,NULL)",
        "INSERT INTO user_portrait (club_id,guest_id) VALUES (2,42),(3,42)",
    ]
    try:
        for sql in schema:
            execute(sql)
        conn = connect()
        with conn.cursor() as cur:
            migration = importlib.import_module("migrations.versions.0028_guest_pulse")
            migration.upgrade(cur)
            migration.upgrade(cur)
        conn.commit()
        conn.close()
        for i, days in enumerate(range(0, 151, 5), 1):
            execute(
                "INSERT INTO guest_sessions VALUES (%s,2,42,%s,%s)",
                (i, NOW - timedelta(days=days, hours=2), NOW - timedelta(days=days)),
            )
        yield connect, execute
    finally:
        if admin:
            with admin.cursor() as cur:
                cur.execute(f"DROP DATABASE `{name}`")
            admin.close()


def run(connect, **kwargs):
    conn = connect()
    try:
        return refresh_club(conn, 2, now_utc=NOW, **kwargs)
    finally:
        conn.close()


def test_backfill_idempotent_club_scoped_and_no_lookahead(database):
    connect, sql = database
    assert run(connect)["guests"] == 1
    history = sql("SELECT * FROM guest_score_history WHERE club_id=2 ORDER BY snapshot_date")
    assert len(history) == 31
    assert len({r["snapshot_date"] for r in history}) == 31
    assert all(r["engagement_score"] == 0 for r in history[:-1])
    assert history[-1]["engagement_score"] == 20
    assert sql("SELECT * FROM guest_pulse_current WHERE club_id=3") == []
    before = [r["detail_json"] for r in history]
    run(connect, backfill=True)
    assert [
        r["detail_json"] for r in sql("SELECT * FROM guest_score_history WHERE club_id=2 ORDER BY snapshot_date")
    ] == before
    conn = connect()
    try:
        current = get_current(conn, 2)
        assert current[0]["health"]["baseline_days"] == 30
        assert current[0]["engagement"]["baseline_days"] == 30
        assert current[0]["engagement"]["baseline_estimated"]
    finally:
        conn.close()


def test_source_change_queues_and_refreshes_current_but_not_daily_snapshot(database):
    connect, sql = database
    run(connect)
    assert sql("SELECT * FROM guest_pulse_dirty WHERE club_id=2") == []
    sql("INSERT INTO guest_case_openings VALUES (2,42,%s)", (NOW - timedelta(hours=1),))
    assert sql("SELECT * FROM guest_pulse_dirty WHERE club_id=2")
    assert run(connect)["status"] == "updated"
    current = json.loads(sql("SELECT detail_json FROM guest_pulse_current WHERE club_id=2")[0]["detail_json"])
    assert current["engagement"]["cb_actions_30d"] == 1
    assert current["engagement"]["score"] == 48
    assert (
        sql("SELECT engagement_score FROM guest_score_history WHERE club_id=2 AND snapshot_date=%s", (NOW.date(),))[0][
            "engagement_score"
        ]
        == 20
    )


def test_rolled_back_source_does_not_queue_or_score(database):
    connect, sql = database
    run(connect)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO guest_case_openings VALUES (2,42,%s)", (NOW,))
    conn.rollback()
    conn.close()
    assert sql("SELECT * FROM guest_pulse_dirty") == []
    assert run(connect)["status"] == "unchanged"


def test_daily_refresh_without_new_visits_and_status_transition(database):
    connect, sql = database
    run(connect)
    conn = connect()
    try:
        refresh_club(conn, 2, now_utc=NOW + timedelta(days=65))
    finally:
        conn.close()
    current = sql("SELECT * FROM guest_pulse_current WHERE club_id=2")[0]
    assert current["lifecycle_status"] == "CHURNED"
    assert current["health_score"] <= 15
    assert sql("SELECT * FROM guest_lifecycle_events WHERE club_id=2 AND to_status='CHURNED'")


def test_failure_rolls_back_scores_history_events_and_retains_dirty(database, monkeypatch):
    from app.services import guest_pulse

    connect, sql = database
    run(connect)
    before = sql("SELECT * FROM guest_pulse_current")
    sql("INSERT INTO guest_case_openings VALUES (2,42,%s)", (NOW,))

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(guest_pulse, "add_history", fail)
    with pytest.raises(RuntimeError):
        run(connect)
    assert sql("SELECT * FROM guest_pulse_current") == before
    assert sql("SELECT * FROM guest_pulse_dirty")


def test_deleted_guest_disappears_and_malformed_sessions_are_excluded(database):
    connect, sql = database
    sql("INSERT INTO guest_sessions VALUES (1000,2,43,%s,%s)", (NOW, NOW - timedelta(hours=1)))
    assert run(connect)["guests"] == 1
    sql("DELETE FROM guests WHERE club_id=2 AND guest_id=42")
    assert run(connect)["guests"] == 0
    assert sql("SELECT * FROM guest_pulse_current") == []


def test_future_conversion_is_not_counted_before_actual_credit(database):
    connect, sql = database
    sql("INSERT INTO cm_bonus_redeem_requests VALUES (2,42,'credited',%s)", (NOW + timedelta(days=1),))
    run(connect)
    row = json.loads(sql("SELECT detail_json FROM guest_pulse_current")[0]["detail_json"])
    assert row["engagement"]["cb_actions_30d"] == 0


def test_selected_and_completed_contracts_are_counted_in_engagement(database):
    connect, sql = database
    sql(
        "INSERT INTO guest_game_contracts VALUES (2,42,'completed',%s,%s)",
        (NOW - timedelta(days=2), NOW - timedelta(days=1)),
    )

    run(connect, force=True)

    row = json.loads(sql("SELECT detail_json FROM guest_pulse_current")[0]["detail_json"])
    assert row["engagement"]["contracts_selected_30d"] == 1
    assert row["engagement"]["contracts_completed_30d"] == 1
    assert row["engagement"]["cb_actions_30d"] == 2


@pytest.fixture
def pulse_client(database, monkeypatch):
    import app.core as core
    from app.main import app
    from app.routes.owner import guest_pulse

    connect, sql = database
    run(connect)
    monkeypatch.setattr(guest_pulse, "get_db_connection", connect)
    monkeypatch.setattr(core, "is_club_service_enabled", lambda cid: True)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "owner"
        sess["club_id"] = 2
        sess["club_name"] = "Test"
        sess[core.CSRF_SESSION_KEY] = "pulse-test-csrf"
    return client


def test_api_filters_counts_and_detail_club_scope(pulse_client):
    data = pulse_client.get("/owner/api/guest-pulse").get_json()
    assert data["ok"] and data["total"] == 1
    assert sum(a["count"] for a in data["audiences"]) == data["total"]
    assert all(a["count"] == a["total"] for a in data["audiences"])
    assert pulse_client.get("/owner/api/guest-pulse?health_min=NaN").status_code == 400
    assert pulse_client.get("/owner/api/guest-pulse?metric=invalid").status_code == 400
    segmented = pulse_client.get("/owner/api/guest-pulse?segment=high_value_at_risk").get_json()
    assert segmented["total"] == 0
    assert sum(audience["count"] for audience in segmented["audiences"]) == 0
    assert pulse_client.get("/owner/api/guest-pulse/guests/43").status_code == 404
    with pulse_client.session_transaction() as sess:
        sess["club_id"] = 3
    assert pulse_client.get("/owner/api/guest-pulse/guests/42").status_code == 404


def test_stage_navigation_and_role_gate(pulse_client):
    response = pulse_client.get("/owner/guest-pulse")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Пульс гостя" in html
    assert 'class="gp-audience-cards"' in html
    assert 'id="gpDistributionTotal"' in html
    assert 'id="gpDistributionLegend"' in html
    assert 'id="gpChartSectors"' in html
    assert 'id="gpChartLabels"' in html
    assert 'id="gpChartIncludeWithout"' in html
    assert 'id="gpSegments"' in html
    assert 'id="gpAudienceDialog"' in html
    assert 'id="gpAudienceSearch"' in html
    assert 'id="gpAudienceAverage"' in html
    assert 'id="gpGuestsPanel"' not in html
    assert 'id="gpSegment"' not in html
    assert 'id="gpWithTelegram"' not in html
    assert 'data-slider="health"' not in html
    assert 'data-slider="value"' not in html
    assert 'data-slider="engagement"' not in html
    with pulse_client.session_transaction() as sess:
        sess["role"] = "reception"
    assert pulse_client.get("/owner/api/guest-pulse").status_code == 302


def test_selection_uses_entire_server_audience_and_requires_csrf(pulse_client, database):
    assert pulse_client.post("/owner/api/guest-pulse/selection", json={}).status_code == 400
    result = pulse_client.post(
        "/owner/api/guest-pulse/selection",
        json={"filters": {}, "guest_ids": [999]},
        headers={"X-CSRFToken": "pulse-test-csrf"},
    )
    assert result.status_code == 200
    assert result.get_json()["count"] == 1
    _, sql = database
    selection = json.loads(sql("SELECT selection_json FROM guest_pulse_selections")[0]["selection_json"])
    assert selection["guest_ids"] == [42]


def test_crm_handoff_idempotent_and_cannot_use_other_clubs_selection(pulse_client, database, monkeypatch):
    from app.routes.owner import crm

    connect, sql = database
    monkeypatch.setattr(crm, "get_db_connection", connect)
    calls = []
    monkeypatch.setattr(
        crm,
        "get_recipient_rows_for_guest_ids",
        lambda conn, cid, ids: [{"guest_id": i, "telegram_id": 100} for i in ids],
    )

    def create(**kwargs):
        calls.append(kwargs)
        return {"mailing_id": 123, "recipients_count": len(kwargs["recipients"])}

    monkeypatch.setattr(crm, "create_mailing_for_recipients", create)
    monkeypatch.setattr(crm, "_start_crm_mailing_worker", lambda mid: None)
    headers = {"X-CSRFToken": "pulse-test-csrf"}
    pulse_client.post("/owner/api/guest-pulse/selection", json={}, headers=headers)
    key = sql("SELECT id FROM guest_pulse_selections")[0]["id"]
    payload = {"pulse_selection": key, "guest_ids": [999], "message_text": "Тест без отправки"}
    assert pulse_client.post("/owner/api/crm-pulse/interact", json=payload, headers=headers).status_code == 200
    assert pulse_client.post("/owner/api/crm-pulse/interact", json=payload, headers=headers).status_code == 200
    assert len(calls) == 1 and calls[0]["recipients"][0]["guest_id"] == 42
    assert calls[0]["filters_json"]["type"] == "guest_pulse"
    with pulse_client.session_transaction() as sess:
        sess["club_id"] = 3
    assert pulse_client.post("/owner/api/crm-pulse/interact", json=payload, headers=headers).status_code == 404


def test_reconstructed_engagement_starts_at_first_known_authorization(database):
    connect, sql = database
    sql(
        "INSERT INTO guest_wheel_token_transactions VALUES (2,42,'first_authorization',%s)", (NOW - timedelta(days=20),)
    )
    run(connect)
    history = sql("SELECT * FROM guest_score_history WHERE club_id=2 ORDER BY snapshot_date")
    before = [r for r in history if r["snapshot_date"] < NOW.date() - timedelta(days=20)]
    after = [r for r in history if NOW.date() - timedelta(days=19) <= r["snapshot_date"] < NOW.date()]
    assert all(r["engagement_score"] == 0 for r in before)
    assert all(r["engagement_score"] == 20 for r in after)
    assert all(json.loads(r["detail_json"])["engagement"]["estimated"] for r in after)


def test_selection_preview_keeps_frozen_guests_even_if_visit_data_changes(pulse_client, database):
    from flask import session

    from app.main import app
    from app.routes.owner.guest_pulse import selection_group

    connect, sql = database
    pulse_client.post("/owner/api/guest-pulse/selection", json={}, headers={"X-CSRFToken": "pulse-test-csrf"})
    key = sql("SELECT id FROM guest_pulse_selections")[0]["id"]
    sql("DELETE FROM guest_pulse_current WHERE club_id=2")
    conn = connect()
    try:
        with app.test_request_context():
            session.update(user_id=10, club_id=2)
            group = selection_group(conn, key)
        assert group["total_count"] == 1
        assert group["guests"][0]["guest_id"] == 42
        assert group["guests"][0]["has_telegram"]
    finally:
        conn.close()


@pytest.fixture
def mixed_pulse_audience(pulse_client, database):
    """More than one page, a disconnected guest, and a connected outsider."""
    _, sql = database
    base = json.loads(
        sql("SELECT detail_json FROM guest_pulse_current WHERE club_id=2 AND guest_id=42")[0]["detail_json"]
    )
    base["audience_type"] = "loyal"
    sql("UPDATE guest_pulse_current SET detail_json=%s WHERE club_id=2 AND guest_id=42", (json.dumps(base),))
    for gid in range(44, 58):
        row = json.loads(json.dumps(base))
        row.update(guest_id=gid, name=f"Гость {gid}", audience_type="risk" if gid == 57 else "loyal")
        sql("INSERT INTO guests VALUES (2,%s,%s,NULL,%s)", (gid, row["name"], None if gid == 56 else gid + 1000))
        sql(
            """INSERT INTO guest_pulse_current
            (club_id,guest_id,health_score,value_score,engagement_score,lifecycle_status,audience_type,calculated_at,detail_json)
            SELECT club_id,%s,health_score,value_score,engagement_score,lifecycle_status,audience_type,calculated_at,%s
            FROM guest_pulse_current WHERE club_id=2 AND guest_id=42""",
            (gid, json.dumps(row)),
        )
    return [42, *range(44, 56)]


def test_telegram_counts_and_selection_cover_full_filtered_audience(pulse_client, database, mixed_pulse_audience):
    _, sql = database
    data = pulse_client.get("/owner/api/guest-pulse?audience_type=loyal").get_json()
    assert data["selected_count"] == 14 and len(data["guests"]) == 10
    assert data["selected_telegram_count"] == 13 and data["selected_without_telegram_count"] == 1
    assert all(a["telegram_count"] + a["without_telegram_count"] == a["count"] for a in data["audiences"])
    loyal = next(a for a in data["audiences"] if a["key"] == "loyal")
    assert loyal["telegram_count"] == 13 and loyal["without_telegram_count"] == 1
    assert data["selected_average_score"] is not None
    assert isinstance(data["guests"][0]["segments"], list)
    assert "last_visit_date" in data["guests"][0]
    assert "phone" in data["guests"][0]
    headers = {"X-CSRFToken": "pulse-test-csrf"}
    response = pulse_client.post(
        "/owner/api/guest-pulse/selection",
        headers=headers,
        json={"filters": {"audience_type": "loyal"}, "guest_ids": [57]},
    )
    assert response.status_code == 200 and response.get_json()["count"] == 13
    saved = json.loads(sql("SELECT selection_json FROM guest_pulse_selections")[0]["selection_json"])
    assert sorted(saved["guest_ids"]) == mixed_pulse_audience


def test_audience_drawer_search_and_contact_filters(pulse_client, mixed_pulse_audience):
    searched = pulse_client.get("/owner/api/guest-pulse?audience_type=loyal&search=Гость+45").get_json()
    assert searched["selected_count"] == 1
    assert searched["guests"][0]["guest_id"] == 45
    without = pulse_client.get("/owner/api/guest-pulse?audience_type=loyal&contact=without").get_json()
    assert without["selected_count"] == 1
    assert without["selected_telegram_count"] == 0
    assert without["guests"][0]["guest_id"] == 56


def test_audience_drawer_handoff_keeps_search_filter(pulse_client, database, mixed_pulse_audience):
    response = pulse_client.post(
        "/owner/api/guest-pulse/selection",
        headers={"X-CSRFToken": "pulse-test-csrf"},
        json={"filters": {"audience_type": "loyal", "search": "Гость 45"}},
    )
    assert response.status_code == 200
    _, sql = database
    saved = json.loads(sql("SELECT selection_json FROM guest_pulse_selections")[0]["selection_json"])
    assert saved["guest_ids"] == [45]


@pytest.mark.parametrize("mode", ["audience", "guest", "deviations"])
def test_telegram_disconnect_is_live_without_score_refresh(pulse_client, database, mode):
    _, sql = database
    # Cached Engagement still says connected, but current Telegram has been removed.
    sql("UPDATE guests SET telegram_id=NULL WHERE club_id=2 AND guest_id=42")
    data = pulse_client.get("/owner/api/guest-pulse").get_json()
    assert data["selected_telegram_count"] == 0 and data["selected_without_telegram_count"] == 1
    assert not data["guests"][0]["has_telegram"]
    assert not pulse_client.get("/owner/api/guest-pulse/guests/42").get_json()["guest"]["has_telegram"]
    response = pulse_client.post(
        "/owner/api/guest-pulse/selection",
        headers={"X-CSRFToken": "pulse-test-csrf"},
        json={"mode": mode, "guest_id": 42},
    )
    assert response.status_code == 400 and "Telegram" in response.get_json()["error"]
    assert not sql("SELECT id FROM guest_pulse_selections")


def test_send_rechecks_telegram_and_cannot_expand_frozen_audience(
    pulse_client, database, mixed_pulse_audience, monkeypatch
):
    from app.routes.owner import crm
    from app.services.guest_pulse import rows

    connect, sql = database
    monkeypatch.setattr(crm, "get_db_connection", connect)
    headers = {"X-CSRFToken": "pulse-test-csrf"}
    pulse_client.post("/owner/api/guest-pulse/selection", json={"filters": {"audience_type": "loyal"}}, headers=headers)
    key = sql("SELECT id FROM guest_pulse_selections")[0]["id"]
    sql("UPDATE guests SET telegram_id=NULL WHERE club_id=2 AND guest_id=44")

    def recipients(conn, cid, ids):
        return rows(conn, "SELECT guest_id,telegram_id FROM guests WHERE club_id=%s", (cid,))

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return {"mailing_id": 456, "recipients_count": len(kwargs["recipients"])}

    monkeypatch.setattr(crm, "get_recipient_rows_for_guest_ids", recipients)
    monkeypatch.setattr(crm, "create_mailing_for_recipients", create)
    monkeypatch.setattr(crm, "_start_crm_mailing_worker", lambda mid: None)
    response = pulse_client.post(
        "/owner/api/crm-pulse/interact",
        headers=headers,
        json={"pulse_selection": key, "guest_ids": [57], "message_text": "Тест без отправки"},
    )
    assert response.status_code == 200
    assert sorted(r["guest_id"] for r in calls[0]["recipients"]) == [gid for gid in mixed_pulse_audience if gid != 44]


def test_audience_sorts_connected_before_pagination(pulse_client, database, mixed_pulse_audience):
    _, sql = database
    # Put a disconnected guest ahead of connected guests by health/name.
    row = json.loads(
        sql("SELECT detail_json FROM guest_pulse_current WHERE club_id=2 AND guest_id=56")[0]["detail_json"]
    )
    row["health"]["score"] = 0
    row["name"] = "AAA"
    sql("UPDATE guest_pulse_current SET detail_json=%s WHERE club_id=2 AND guest_id=56", (json.dumps(row),))
    first = pulse_client.get("/owner/api/guest-pulse?audience_type=loyal").get_json()["guests"]
    second = pulse_client.get("/owner/api/guest-pulse?audience_type=loyal&page=2").get_json()["guests"]
    assert all(row["has_telegram"] for row in first)
    assert all(row["has_telegram"] for row in second[:-1])
    assert second[-1]["guest_id"] == 56 and not second[-1]["has_telegram"]


def test_audience_can_sort_all_rows_by_overall_score(pulse_client, database, mixed_pulse_audience):
    _, sql = database
    for guest_id, score in ((44, 0), (45, 100)):
        row = json.loads(
            sql(
                "SELECT detail_json FROM guest_pulse_current WHERE club_id=2 AND guest_id=%s",
                (guest_id,),
            )[0]["detail_json"]
        )
        for metric in ("health", "value", "engagement"):
            row[metric]["score"] = score
        sql(
            "UPDATE guest_pulse_current SET detail_json=%s WHERE club_id=2 AND guest_id=%s",
            (json.dumps(row), guest_id),
        )

    ascending = pulse_client.get(
        "/owner/api/guest-pulse?audience_type=loyal&sort=overall&sort_direction=asc"
    ).get_json()
    descending = pulse_client.get(
        "/owner/api/guest-pulse?audience_type=loyal&sort=overall&sort_direction=desc"
    ).get_json()
    assert ascending["guests"][0]["guest_id"] == 44
    assert ascending["guests"][0]["overall"]["score"] == 0
    assert descending["guests"][0]["guest_id"] == 45
    assert descending["guests"][0]["overall"]["score"] == 100


def test_selection_returns_inline_form_audience_with_stage_block(pulse_client, database, monkeypatch):
    monkeypatch.setenv("DISABLE_OUTBOUND_MESSAGES", "1")
    response = pulse_client.get("/owner/guest-pulse")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="crmPulseModal"' in html
    assert "window.CRM_OUTBOUND_DISABLED = true" in html
    assert 'id="crmAnalysisRulesContainer"' not in html
    selection = pulse_client.post(
        "/owner/api/guest-pulse/selection", json={}, headers={"X-CSRFToken": "pulse-test-csrf"}
    ).get_json()
    assert selection["group"]["guest_ids"] == [42]
    assert all(guest["has_telegram"] for guest in selection["group"]["guests"])
    assert selection["group"]["selection_id"]
