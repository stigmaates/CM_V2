"""Transactional scenarios use temporary SQLite by default.

Set MANAGED_DROPS_TEST_SOCKET for native MySQL row-lock verification. Each MySQL
test creates and drops its own random database; application DB settings are never used.
"""

import importlib
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

import pymysql
import pytest
from flask import render_template, session
from pymysql.cursors import DictCursor

from app.main import app
from app.services import cases, wheel
from app.services import managed_drops as drops


class SQLiteCursor:
    """Local transactional fallback; MySQL mode runs the original SQL unchanged."""

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params=()):
        query = query.replace("%s", "?").replace(" FOR UPDATE", "")
        query = query.replace("BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        query = query.replace("INT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        query = re.sub(r"UNIQUE KEY \w+", "UNIQUE", query)
        query = re.sub(r",\s*KEY idx_managed_drop_history \(club_id, id\)", "", query)
        query = query.split(" ENGINE=InnoDB")[0]
        params = tuple(p.isoformat(sep=" ") if isinstance(p, datetime) else p for p in params)
        try:
            self.result = self.connection.execute(query, params)
        except sqlite3.IntegrityError as exc:
            raise pymysql.err.IntegrityError(1062, str(exc)) from exc
        self.lastrowid = self.result.lastrowid
        self.rowcount = self.result.rowcount

    def fetchall(self):
        rows = [dict(row) for row in self.result.fetchall()]
        for row in rows:
            for field in ("created_at", "finished_at"):
                if row.get(field):
                    row[field] = datetime.fromisoformat(row[field])
        return rows

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class SQLiteConnection:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        # SQLite has database-wide writer locks, unlike MySQL row locks.
        self.db.execute("BEGIN IMMEDIATE")

    def cursor(self):
        return SQLiteCursor(self.db)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()


@pytest.fixture
def drop_db(monkeypatch, tmp_path):
    socket = os.environ.get("MANAGED_DROPS_TEST_SOCKET")
    name = "managed_drop_test_" + uuid4().hex
    admin = None
    if socket:
        admin = pymysql.connect(unix_socket=socket, user="root", autocommit=True)
        with admin.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{name}`")

    def connect():
        if not socket:
            return SQLiteConnection(tmp_path / "managed-drops.sqlite")
        return pymysql.connect(unix_socket=socket, user="root", database=name, cursorclass=DictCursor)

    def sql(query, params=()):
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    try:
        schema = [
            "CREATE TABLE guests (guest_id INT, club_id INT, fio VARCHAR(255), phone VARCHAR(80))",
            "CREATE TABLE balances (club_id INT, guest_id INT, balance INT, PRIMARY KEY (club_id, guest_id))",
            """CREATE TABLE club_cases (id INT PRIMARY KEY, club_id INT, name VARCHAR(255), description TEXT,
                image_url TEXT, badge_label TEXT, badge_color VARCHAR(7), price_tokens INT,
                is_active INT DEFAULT 1, sort_order INT DEFAULT 0)""",
            """CREATE TABLE club_case_items (id INT PRIMARY KEY, case_id INT, club_id INT, name VARCHAR(255),
                description TEXT, image_url TEXT, bonus_amount INT DEFAULT 0, token_amount INT DEFAULT 0,
                contract_refresh_amount INT DEFAULT 0, probability INT, rarity_label TEXT,
                is_active INT DEFAULT 1, sort_order INT DEFAULT 0)""",
            """CREATE TABLE club_wheel_prizes (id INT PRIMARY KEY, club_id INT, name VARCHAR(255),
                description TEXT, image_url TEXT, icon_emoji TEXT, bonus_amount INT DEFAULT 0,
                token_amount INT DEFAULT 0, probability INT, is_active INT DEFAULT 1, sort_order INT DEFAULT 0)""",
            "CREATE TABLE club_wheel_settings (club_id INT PRIMARY KEY, is_enabled INT)",
            """CREATE TABLE guest_case_openings (id INT AUTO_INCREMENT PRIMARY KEY, club_id INT, guest_id INT,
                case_id INT, item_id INT, spent_tokens INT, created_at DATETIME)""",
            """CREATE TABLE guest_wheel_spins (id INT AUTO_INCREMENT PRIMARY KEY, club_id INT, guest_id INT,
                prize_id INT, spent_tokens INT, created_at DATETIME)""",
            "CREATE TABLE rewards (id INT AUTO_INCREMENT PRIMARY KEY, amount INT)",
            "CREATE TABLE claims (id INT AUTO_INCREMENT PRIMARY KEY, prize_name VARCHAR(255))",
            "INSERT INTO guests VALUES (42, 2, 'Иван Тестовый', '9991234567'), (42, 3, 'Другой клуб', '9991234567')",
            "INSERT INTO balances VALUES (2, 42, 10), (3, 42, 10)",
            "INSERT INTO club_cases (id, club_id, name, price_tokens) VALUES (1, 2, 'CS2', 3), (99, 3, 'Другой', 3)",
            """INSERT INTO club_case_items (id, case_id, club_id, name, probability, bonus_amount) VALUES
                (1, 1, 2, 'Обычный', 100, 100), (2, 1, 2, 'Редкий', 0, 300),
                (3, 1, 2, 'Футболка', 0, 0), (99, 99, 3, 'Чужой', 100, 500)""",
            """INSERT INTO club_wheel_prizes (id, club_id, name, probability, bonus_amount) VALUES
                (1, 2, 'Обычный', 100, 100), (2, 2, 'Редкий', 0, 300), (3, 2, 'Футболка', 0, 0)""",
            "INSERT INTO club_wheel_settings VALUES (2, 1)",
        ]
        for query in schema:
            sql(query)
        conn = connect()
        with conn.cursor() as cur:
            importlib.import_module("migrations.versions.0027_managed_drops").upgrade(cur)
            importlib.import_module("migrations.versions.0027_managed_drops").upgrade(cur)
        conn.commit()
        conn.close()

        def balance(cursor, guest_id, club_id):
            cursor.execute(
                "SELECT balance FROM balances WHERE club_id=%s AND guest_id=%s FOR UPDATE", (club_id, guest_id)
            )
            return cursor.fetchone()["balance"]

        def tokens(*, cursor, guest_id, club_id, amount, **kwargs):
            cursor.execute(
                "UPDATE balances SET balance=balance+%s WHERE club_id=%s AND guest_id=%s", (amount, club_id, guest_id)
            )
            return True

        def reward(*, cursor, amount, **kwargs):
            cursor.execute("INSERT INTO rewards (amount) VALUES (%s)", (amount,))
            return True

        def wheel_reward(*, cursor, prize, **kwargs):
            return reward(cursor=cursor, amount=prize["bonus_amount"]) if prize["bonus_amount"] else False

        def claim(*, cursor, prize, **kwargs):
            cursor.execute("INSERT INTO claims (prize_name) VALUES (%s)", (prize["name"],))
            return cursor.lastrowid

        for module in (cases, wheel, drops):
            monkeypatch.setattr(module, "get_db_connection", connect)
        for module in (cases, wheel):
            for attr in (
                "ensure_case_tables",
                "ensure_token_tables",
                "ensure_cm_bonus_tables",
                "ensure_prize_claim_tables",
                "ensure_wheel_prize_bonus_columns",
            ):
                if hasattr(module, attr):
                    monkeypatch.setattr(module, attr, lambda cur: None)
            monkeypatch.setattr(module, "_get_balance_for_update", balance)
            monkeypatch.setattr(module, "_add_token_transaction", tokens)
            monkeypatch.setattr(module, "create_prize_claim", claim)
            monkeypatch.setattr(module, "notify_prize_claim_admin_chat", lambda claim_id: None)
        monkeypatch.setattr(cases, "get_prize_claim_by_spin_id", lambda spin_id: None)
        monkeypatch.setattr(cases, "add_cm_bonus_transaction", reward)
        monkeypatch.setattr(wheel, "award_cm_bonuses_for_wheel_prize", wheel_reward)
        yield sql
    finally:
        if admin:
            with admin.cursor() as cur:
                cur.execute(f"DROP DATABASE `{name}`")
            admin.close()


def assign(**kwargs):
    options = dict(
        club_id=2,
        guest_id=42,
        phone="+7 (999) 123-45-67",
        target="case:1",
        prize_id=2,
        actor_user_id=7,
        actor_name="Владелец",
        request_key=str(uuid4()),
    )
    options.update(kwargs)
    return drops.create_managed_drop(**options)


def test_case_assignment_is_one_shot_and_charges_normal_price(drop_db):
    assign()
    assert cases.open_case(42, 2, 1)["item"]["id"] == 2
    assert cases.open_case(42, 2, 1)["item"]["id"] == 1
    assert drop_db("SELECT balance FROM balances WHERE club_id=2")[0]["balance"] == 4
    assert [r["amount"] for r in drop_db("SELECT amount FROM rewards ORDER BY id")] == [300, 100]
    row = drop_db("SELECT * FROM managed_drops")[0]
    assert row["status"] == "consumed" and row["opening_id"] == 1


def test_wheel_returns_the_actual_assigned_prize(drop_db):
    assign(target="wheel:0")
    spin_id, prize = wheel.save_guest_wheel_spin(42, 2, return_prize=True)
    assert prize["id"] == 2
    assert drop_db("SELECT prize_id FROM guest_wheel_spins WHERE id=%s", (spin_id,))[0]["prize_id"] == 2
    assert wheel.save_guest_wheel_spin(42, 2, return_prize=True)[1]["id"] == 1
    assert "managed" not in str(wheel.serialize_wheel_prize(prize))


@pytest.mark.parametrize("target", ["case:1", "wheel:0"])
def test_failed_reward_rolls_back_opening_charge_and_assignment(drop_db, monkeypatch, target):
    assign(target=target)

    def fail(**kwargs):
        raise RuntimeError("simulated reward failure")

    module, function = (
        (cases, "add_cm_bonus_transaction") if target == "case:1" else (wheel, "award_cm_bonuses_for_wheel_prize")
    )
    monkeypatch.setattr(module, function, fail)
    with pytest.raises(RuntimeError):
        cases.open_case(42, 2, 1) if target == "case:1" else wheel.save_guest_wheel_spin(42, 2)
    assert drop_db("SELECT balance FROM balances WHERE club_id=2")[0]["balance"] == 10
    assert drop_db("SELECT status FROM managed_drops")[0]["status"] == "pending"
    assert drop_db("SELECT * FROM guest_case_openings") == []
    assert drop_db("SELECT * FROM guest_wheel_spins") == []


def test_no_tokens_keeps_assignment_pending(drop_db):
    assign()
    drop_db("UPDATE balances SET balance=0 WHERE club_id=2")
    with pytest.raises(ValueError, match="no_tokens"):
        cases.open_case(42, 2, 1)
    assert drop_db("SELECT status FROM managed_drops")[0]["status"] == "pending"


@pytest.mark.parametrize("free", [False, True])
def test_concurrent_case_openings_consume_assignment_only_once(drop_db, free):
    assign()
    if free:
        drop_db("UPDATE club_cases SET price_tokens=0 WHERE id=1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cases.open_case(42, 2, 1)["item"]["id"], range(2)))
    assert sorted(results) == [1, 2]
    assert len(drop_db("SELECT * FROM guest_case_openings")) == 2


def test_concurrent_wheel_spins_consume_assignment_only_once(drop_db):
    assign(target="wheel:0")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: wheel.save_guest_wheel_spin(42, 2, return_prize=True)[1]["id"], range(2)))
    assert sorted(results) == [1, 2]


def test_club_and_target_isolation_and_cancellation(drop_db):
    drop_id = assign()
    assert not drops.cancel_managed_drop(3, drop_id, 7)
    assert cases.open_case(42, 3, 99)["item"]["id"] == 99
    assert wheel.save_guest_wheel_spin(42, 2, return_prize=True)[1]["id"] == 1
    assert drop_db("SELECT status FROM managed_drops")[0]["status"] == "pending"
    assert drops.cancel_managed_drop(2, drop_id, 7)
    assert cases.open_case(42, 2, 1)["item"]["id"] == 1
    with pytest.raises(ValueError):
        assign(target="case:99", prize_id=99)
    with pytest.raises(ValueError):
        assign(guest_id=12345)


def test_duplicate_form_never_arms_second_drop_even_after_consumption(drop_db):
    key = str(uuid4())
    drop_id = assign(request_key=key)
    with pytest.raises(ValueError, match="уже есть назначение"):
        assign()
    cases.open_case(42, 2, 1)
    assert assign(request_key=key) == drop_id
    assert len(drop_db("SELECT * FROM managed_drops")) == 1
    assert cases.open_case(42, 2, 1)["item"]["id"] == 1


def test_disabled_prize_falls_back_and_records_reason(drop_db):
    assign()
    drop_db("UPDATE club_case_items SET is_active=0 WHERE id=2")
    assert cases.open_case(42, 2, 1)["item"]["id"] == 1
    row = drop_db("SELECT * FROM managed_drops")[0]
    assert row["status"] == "invalid" and row["reason"]


def test_test_mode_does_not_consume_real_assignment(drop_db):
    assign()
    assert cases.open_case(42, 2, 1, test_mode=True)["item"]["id"] == 1
    assert drop_db("SELECT status FROM managed_drops")[0]["status"] == "pending"


@pytest.mark.parametrize("target", ["case:1", "wheel:0"])
def test_physical_prize_creates_standard_claim(drop_db, target):
    assign(target=target, prize_id=3)
    cases.open_case(42, 2, 1) if target == "case:1" else wheel.save_guest_wheel_spin(42, 2)
    assert drop_db("SELECT prize_name FROM claims")[0]["prize_name"] == "Футболка"


def test_history_is_club_scoped_paginated_and_preserves_snapshots(drop_db):
    for _ in range(6):
        drops.cancel_managed_drop(2, assign(), 7)
    page = drops.get_managed_drop_page(2, timezone_name="Asia/Yekaterinburg")
    assert page["total"] == 6 and len(page["history"]) == 5
    assert len(drops.get_managed_drop_page(2, show_all=True)["history"]) == 6
    assert drops.get_managed_drop_page(3)["total"] == 0
    drop_db("DELETE FROM club_cases WHERE id=1")
    assert drops.get_managed_drop_page(2)["history"][0]["target_name"] == "CS2"


def test_managed_drop_tab_renders_search_form_and_history_without_db():
    with app.test_request_context("/owner/settings?tab=managed-drops"):
        session["role"] = "owner"
        html = render_template(
            "owner/settings.html",
            active_tab="managed-drops",
            drop_phone="9991234567",
            drop_request_key=str(uuid4()),
            club_timezone_label="Уфа — UTC+5",
            drop_page={
                "guests": [{"guest_id": 42, "fio": "Иван Тестовый", "phone": "9991234567"}],
                "targets": [{"key": "case:1", "name": "CS2", "prizes": [{"id": 2, "name": "Редкий"}]}],
                "history": [],
                "total": 6,
                "page": 1,
                "pages": 1,
                "show_all": False,
            },
        )
    assert html.index("tab=managed-drops") < html.index("tab=guests")
    assert "Геймификация" in html and "Управление" in html
    assert "Номер телефона в системе клуба" in html
    assert "Иван Тестовый" in html and "Редкий" in html
    assert 'name="csrf_token"' in html and 'name="request_key"' in html
    assert "Показать всю историю" in html


def test_reception_cannot_assign_managed_drop(monkeypatch):
    from app.routes.owner.settings import settings_managed_drop_create

    with app.test_request_context("/owner/settings/managed-drops", method="POST"):
        session.update(user_id=8, club_id=2, role="reception")
        response = settings_managed_drop_create()
    assert response.status_code == 302
    assert "/reception" in response.location
