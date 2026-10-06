"""Read actual imported Gizmo rows through common guest features.

SQLite only translates SQL dialect and datetime decoding; domain calculations,
wallet writes and reception reads use their production implementations.
"""

from datetime import UTC, date, datetime

import pytest

from app.integrations.gizmo_import import collect, save
from app.services import cm_bonuses, missions, prize_claims, reception, wheel
from tests.test_gizmo_history_references import HistoryAPI
from tests.test_gizmo_store import Connection, Cursor

CLUB = 900001


class GuestCursor(Cursor):
    def execute(self, sql, params=()):
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
        super().execute(sql, params)

    def fetchall(self):
        rows = super().fetchall()
        for row in rows:
            for key in ("date_start", "date_stop"):
                if isinstance(row.get(key), str):
                    row[key] = datetime.fromisoformat(row[key])
        return rows

    @property
    def rowcount(self):
        return self.cur.rowcount

    @property
    def lastrowid(self):
        return self.cur.lastrowid if self.cur.rowcount else 0


class GuestConnection(Connection):
    def cursor(self):
        return GuestCursor(self)

    def close(self):
        pass  # Services share this test database; fixture owns its lifetime.


@pytest.fixture
def imported(monkeypatch):
    conn = GuestConnection()
    api = HistoryAPI()
    # Friday UTC, Saturday in Ufa. Two sessions merge into one visit.
    api.data["sessions"] = [
        dict(id=123, userId=10, span=3600, startTime="2026-10-02T19:30:00Z", endTime="2026-10-02T20:30:00Z"),
        dict(id=124, userId=10, span=3600, startTime="2026-10-02T21:00:00Z", endTime="2026-10-02T22:00:00Z"),
        dict(id=125, userId=10, span=3600, startTime="2026-10-03T20:00:00Z", endTime="2026-10-03T21:00:00Z"),
    ]
    api.data["usersessions"] = [dict(id=n, userId=10, hostId=26, state=2, span=3600) for n in (123, 124, 125)]
    data = collect(
        api, branch_id=1, start=None, end=datetime(2026, 10, 5, tzinfo=UTC), cash_method_ids={-1}, full_history=True
    )
    save(conn, CLUB, data)
    # Identical external guest ID and phone in another club must not leak.
    conn.db.execute("INSERT INTO clubs VALUES (2,'langame',1,1)")
    conn.db.execute("INSERT INTO guests (club_id,guest_id,phone,fio) VALUES (2,10,'79001112233','Другой гость')")
    conn.db.execute(
        "INSERT INTO guest_sessions (club_id,id,guest_id,date_start,date_stop) VALUES (2,1,10,'2026-10-03 00:00:00','2026-10-03 05:00:00')"
    )
    conn.commit()
    for module in (missions, wheel, cm_bonuses, reception, prize_claims):
        monkeypatch.setattr(module, "get_db_connection", lambda: conn)
    yield conn
    conn.db.close()


def mission(metric, provider="gizmo"):
    return dict(
        target_metric=metric,
        integration_provider=provider,
        club_timezone="Asia/Yekaterinburg",
        start_at=datetime(2026, 10, 3),
        end_at=datetime(2026, 10, 3, 23, 59, 59),
        config={},
    )


@pytest.mark.parametrize(
    "metric,expected",
    [
        ("visits_count", 1),
        ("weekend_visits_count", 1),
        ("night_visits_count", 1),
        ("day_hours_total", 0),
        ("night_hours_total", 2),
        ("total_hours", 2),
    ],
)
def test_imported_sessions_count_on_club_day_without_other_club(imported, metric, expected):
    assert missions.calculate_mission_progress(10, CLUB, mission(metric)) == expected
    assert missions.calculate_mission_progress(999, CLUB, mission(metric)) == 0


def test_langame_wall_time_does_not_receive_another_timezone_shift(imported):
    assert missions.calculate_mission_progress(10, 2, mission("night_hours_total", "langame")) == 5


def test_gizmo_streak_groups_local_days_and_honors_local_start(imported):
    settings = dict(integration_provider="gizmo", club_timezone="Asia/Yekaterinburg")
    with imported.cursor() as cursor:
        days = wheel._get_visit_days(cursor, 10, CLUB, date(2026, 10, 3), settings=settings)
        assert days == [date(2026, 10, 3), date(2026, 10, 4)]
        assert wheel._get_visit_days(cursor, 10, CLUB, date(2026, 10, 4), settings=settings) == [date(2026, 10, 4)]
    assert [row["reward"] for row in wheel._calculate_streak_rows(days)] == [1, 2]


@pytest.fixture
def wallets(imported, monkeypatch):
    imported.db.executescript("""
        CREATE TABLE cm_bonus_balances (club_id INT,guest_id INT,balance INT,updated_at TEXT,UNIQUE(club_id,guest_id));
        CREATE TABLE guest_wheel_token_balances (club_id INT,guest_id INT,balance INT,updated_at TEXT,UNIQUE(club_id,guest_id));
        CREATE TABLE cm_bonus_transactions (id INTEGER PRIMARY KEY,club_id INT,guest_id INT,amount INT,balance_after INT,
            source_type TEXT,source_id TEXT,description TEXT,status TEXT,expires_at TEXT,expires_status TEXT,created_at TEXT);
        CREATE TABLE guest_wheel_token_transactions (id INTEGER PRIMARY KEY,club_id INT,guest_id INT,amount INT,balance_after INT,
            source_type TEXT,source_id TEXT,description TEXT,expires_at TEXT,expires_status TEXT,created_at TEXT);
        CREATE TABLE cm_bonus_redeem_requests (id INTEGER PRIMARY KEY,club_id INT,guest_id INT,amount INT,status TEXT,error_text TEXT,
            requested_at TEXT,processed_at TEXT,processed_by_username TEXT);
        CREATE TABLE guest_prize_claims (id INTEGER PRIMARY KEY,club_id INT,guest_id INT,spin_id INT,source_type TEXT,source_id TEXT,
            prize_id INT,prize_name TEXT,prize_description TEXT,prize_image_url TEXT,status TEXT,created_at TEXT,
            issued_at TEXT,cancelled_at TEXT,issued_by_username TEXT,UNIQUE(club_id,guest_id,source_type,source_id));
    """)
    monkeypatch.setattr(cm_bonuses, "ensure_cm_bonus_tables", lambda cursor: None)
    monkeypatch.setattr(wheel, "ensure_token_tables", lambda cursor: None)
    monkeypatch.setattr(prize_claims, "ensure_prize_claim_tables", lambda cursor: None)
    return imported


def test_rewards_and_reception_use_same_imported_guest_and_isolate_clubs(wallets):
    imported = wallets
    with imported.cursor() as cursor:
        for club, amount in ((CLUB, 100), (2, 900)):
            assert cm_bonuses.add_cm_bonus_transaction(cursor, 10, club, amount, "mission", "50")
            assert wheel._add_token_transaction(cursor, 10, club, 3, "mission", "50")
            claim = prize_claims.create_prize_claim(
                cursor, 10, club, None, dict(id=50, name="Стикер"), source_type="mission", source_id="50"
            )
            assert claim
        assert not cm_bonuses.add_cm_bonus_transaction(cursor, 10, CLUB, 100, "mission", "50")
        assert not wheel._add_token_transaction(cursor, 10, CLUB, 3, "mission", "50")
    imported.commit()
    result = reception.get_reception_guest_lookup(club_id=CLUB, phone="8 (900) 111-22-33")
    assert result["guest"]["guest_id"] == 10
    assert result["guest"]["bonus_balance"] == 100
    assert result["guest"]["token_balance"] == 3
    assert len(result["bonus_transactions"]) == len(result["token_transactions"]) == len(result["prize_claims"]) == 1
    claim_id = result["prize_claims"][0]["id"]
    assert not prize_claims.mark_prize_claim_issued_by_owner(claim_id, 2)["ok"]
    assert prize_claims.mark_prize_claim_issued_by_owner(claim_id, CLUB)["ok"]
    result = reception.get_reception_guest_lookup(club_id=CLUB, phone="9001112233")
    assert result["prize_claims"][0]["status"] == "issued"
    assert (
        reception.get_reception_guest_lookup(club_id=2, phone="79001112233")["prize_claims"][0]["status"] == "pending"
    )


def test_stage_readonly_runner_checks_imported_guest_features(wallets, monkeypatch):
    from scripts import verify_gizmo_guest_features as audit

    wallets.db.execute("ALTER TABLE clubs ADD COLUMN timezone TEXT DEFAULT 'Asia/Yekaterinburg'")
    wallets.commit()
    monkeypatch.setattr(audit, "require_stage_environment", lambda: None)
    report = audit.verify(CLUB, connection_factory=lambda: wallets)
    assert report["status"] == "complete"
    assert report["guests_checked"] == report["boundary_guests_checked"] == 1
    assert report["reception_guests_checked"] == 1
    assert report["personal_sessions_read"] == 3
    assert report["club_flags"]["service_enabled"] == 0
    assert wallets.records("cm_bonus_transactions") == []
    assert wallets.records("guest_prize_claims") == []


def test_stage_readonly_runner_rejects_wrong_calculation(wallets, monkeypatch):
    from scripts import verify_gizmo_guest_features as audit

    wallets.db.execute("ALTER TABLE clubs ADD COLUMN timezone TEXT DEFAULT 'Asia/Yekaterinburg'")
    wallets.commit()
    monkeypatch.setattr(audit, "require_stage_environment", lambda: None)
    monkeypatch.setattr(missions, "calculate_mission_progress", lambda *args: -1)
    with pytest.raises(ValueError, match="Night mission"):
        audit.verify(CLUB, connection_factory=lambda: wallets)


def test_stage_reader_enforces_mysql_read_only_before_any_queries(monkeypatch):
    from scripts import verify_gizmo_guest_features as audit

    statements = []

    class ReadOnlyConnection:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql):
            statements.append(sql)

    conn = ReadOnlyConnection()
    monkeypatch.setattr(audit, "get_db_connection", lambda: conn)
    assert audit.readonly_connection() is conn
    assert statements == ["SET SESSION TRANSACTION READ ONLY", "SET SESSION MAX_EXECUTION_TIME=15000"]
