import random
from datetime import timedelta
from decimal import Decimal

import pytest

import app.services.game_contracts as game_contracts
from app.services.game_contracts import (
    DOTA_HEROES,
    GameContractError,
    _contract_signature,
    _match_contribution,
    _system_contract_candidates,
    generate_system_contract_pool,
    normalize_contract_template,
    select_contract_templates,
)


def test_template_keeps_reward_per_contract_and_forces_ratio_to_match_period():
    item = normalize_contract_template(
        {
            "game": "cs2",
            "title": "Точный стрелок",
            "description_template": "Закончи матч с K/D не ниже 1,5",
            "metric_type": "kd_ratio",
            "target_value": "1,5",
            "period_type": "week",
            "difficulty": "hard",
            "reward_tokens": "3",
            "reward_bonus": "150",
            "weight": "20",
            "is_active": "1",
        }
    )

    assert item["target_value"] == Decimal("1.50")
    assert item["period_type"] == "match"
    assert item["reward_tokens"] == 3
    assert item["reward_bonus"] == 150


def test_weapon_contract_requires_weapon_condition():
    with pytest.raises(GameContractError, match="оружие"):
        normalize_contract_template(
            {
                "game": "cs2",
                "title": "Калаш решает",
                "description": "Сделай 10 убийств",
                "metric_type": "weapon_kills",
                "target_value": 10,
                "difficulty": "medium",
            }
        )


def test_weekly_pool_contains_two_contracts_of_each_difficulty_without_duplicates():
    templates = [
        {"id": 1, "difficulty": "easy", "metric_type": "matches_played", "weight": 100},
        {"id": 2, "difficulty": "easy", "metric_type": "kills", "weight": 100},
        {"id": 3, "difficulty": "medium", "metric_type": "wins", "weight": 100},
        {"id": 4, "difficulty": "medium", "metric_type": "assists", "weight": 100},
        {"id": 5, "difficulty": "hard", "metric_type": "headshots", "weight": 100},
        {"id": 6, "difficulty": "hard", "metric_type": "weapon_kills", "weight": 100},
    ]

    selected = select_contract_templates(templates, {1, 3}, rng=random.Random(7))

    assert len(selected) == 6
    assert [item["difficulty"] for item in selected].count("easy") == 2
    assert [item["difficulty"] for item in selected].count("medium") == 2
    assert [item["difficulty"] for item in selected].count("hard") == 2
    assert len({item["id"] for item in selected}) == 6
    assert len({item["metric_type"] for item in selected}) == 6


@pytest.mark.parametrize("game", ["cs2", "dota2"])
def test_system_constructor_builds_personal_six_contract_pool(game):
    selected = generate_system_contract_pool(game, rng=random.Random(17))

    assert len(selected) == 6
    assert [item["difficulty"] for item in selected].count("easy") == 2
    assert [item["difficulty"] for item in selected].count("medium") == 2
    assert [item["difficulty"] for item in selected].count("hard") == 2
    assert len({item["id"] for item in selected}) == 6
    assert max(
        [item["metric_type"] for item in selected].count(metric)
        for metric in {item["metric_type"] for item in selected}
    ) <= 2
    assert all(item["reward_tokens"] == 0 for item in selected)
    assert all(item["reward_bonus"] == 0 for item in selected)


def test_dota_hero_contracts_use_full_catalog_and_scale_matches_by_difficulty():
    assert len(DOTA_HEROES) >= 120
    candidates = _system_contract_candidates("dota2", random.Random(31))
    expected_targets = {"easy": Decimal("1.00"), "medium": Decimal("3.00"), "hard": Decimal("5.00")}
    hero_contracts = {}
    hero_ids = set()

    for difficulty, target in expected_targets.items():
        contract = next(item for item in candidates[difficulty] if item["metric_type"] == "hero_played")
        hero_contracts[difficulty] = contract
        hero_ids.add(int(game_contracts._json_loads(contract["conditions_json"])["hero_id"]))
        assert contract["target_value"] == target
        assert "матч" in contract["description_template"]

    assert len(hero_contracts) == 3
    assert len(hero_ids) == 3
    assert hero_ids <= {hero_id for hero_id, _hero_name in DOTA_HEROES}


def test_contract_images_follow_map_weapon_hero_and_tower_conditions():
    map_image = game_contracts._contract_image(
        {"game": "cs2", "metric_type": "map_kills", "conditions_json": '{"map":"de_cache"}'}
    )
    weapon_image = game_contracts._contract_image(
        {"game": "cs2", "metric_type": "weapon_kills", "conditions_json": '{"weapon":"awp"}'}
    )
    hero_image = game_contracts._contract_image(
        {"game": "dota2", "metric_type": "hero_played", "conditions_json": '{"hero_id":2}'}
    )
    cs_kills_image = game_contracts._contract_image(
        {"game": "cs2", "metric_type": "kills", "conditions_json": "{}"}
    )
    dota_support_image = game_contracts._contract_image(
        {"game": "dota2", "metric_type": "assists", "conditions_json": "{}"}
    )
    tower_image = game_contracts._contract_image(
        {
            "game": "dota2",
            "metric_type": "damage",
            "title": "Урон по таверам",
            "conditions_json": "{}",
        }
    )

    assert map_image["image_url"] == "/static/images/cs2/maps/de_cache.jpg"
    assert weapon_image == {
        "image_url": "/static/images/cs2/weapons/awp.png",
        "image_fit": "contain",
        "image_position": "right center",
    }
    assert hero_image["image_url"].endswith("/dota_react/heroes/axe.png")
    assert cs_kills_image["image_url"] == "/static/images/contracts/cs2/kills.webp"
    assert dota_support_image["image_url"] == "/static/images/contracts/dota2/support.webp"
    assert tower_image["image_url"] == "/static/images/contracts/dota2/tower.webp"


def test_active_contract_serialization_keeps_its_contextual_image():
    now = game_contracts._utcnow()
    contract = game_contracts._serialize_contract(
        {
            "id": 17,
            "game": "cs2",
            "metric_type": "headshots",
            "conditions_json": "{}",
            "current_value": 4,
            "target_value": 15,
            "difficulty": "medium",
            "status": "active",
            "expires_at": now + timedelta(days=6),
        },
        now,
    )

    assert contract["image_url"] == "/static/images/contracts/cs2/headshots.webp"
    assert contract["image_fit"] == "cover"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (None, False),
        ({"is_enabled": 0}, False),
        ({"is_enabled": 1}, True),
    ],
)
def test_contract_feature_is_disabled_until_club_enables_it(monkeypatch, row, expected):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            assert "FROM game_contract_settings" in sql
            assert params == (7,)

        def fetchone(self):
            return row

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(game_contracts, "get_db_connection", Connection)

    assert game_contracts.is_game_contracts_enabled(7) is expected


@pytest.mark.parametrize("game", ["cs2", "dota2"])
def test_refreshed_pool_does_not_repeat_previous_contracts(game):
    first = generate_system_contract_pool(game, rng=random.Random(17))
    excluded = {_contract_signature(item) for item in first}

    refreshed = generate_system_contract_pool(
        game,
        rng=random.Random(17),
        excluded_signatures=excluded,
    )

    assert len(refreshed) == 6
    assert not ({_contract_signature(item) for item in refreshed} & excluded)


def test_force_refresh_uses_the_linked_steam_account_and_creates_six_offers(monkeypatch):
    class Cursor:
        def __init__(self):
            self.rows = []
            self.lastrowid = 0
            self.contract_inserts = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            self.rows = []
            if "FROM guest_steam_accounts" in normalized:
                self.rows = [{"id": 1, "steam_id": "76561190000000000"}]
            elif "FROM guest_game_contract_sets" in normalized and normalized.startswith("SELECT"):
                self.rows = [{"id": 41, "status": "active"}]
            elif "COUNT(*) AS completed_count" in normalized:
                self.rows = [{"completed_count": 0}]
            elif normalized.startswith("SELECT metric_type"):
                self.rows = []
            elif "FROM game_contract_reward_settings" in normalized:
                self.rows = []
            elif normalized.startswith("INSERT INTO guest_game_contract_sets"):
                self.lastrowid = 42
            elif normalized.startswith("INSERT INTO guest_game_contracts"):
                self.contract_inserts.append(params)

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def __init__(self):
            self.test_cursor = Cursor()
            self.committed = False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("refresh transaction should not roll back")

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(game_contracts, "get_db_connection", lambda: connection)

    result = game_contracts.reroll_guest_contracts(1, 63253, "dota2", consume_refresh=False)

    assert result["new_set_id"] == 42
    assert connection.committed is True
    assert len(connection.test_cursor.contract_inserts) == 6
    assert all(params[3] == "76561190000000000" for params in connection.test_cursor.contract_inserts)


def test_progress_uses_match_facts_and_contract_conditions():
    match = {
        "map_name": "de_dust2",
        "kills": 12,
        "deaths": 8,
        "assists": 3,
        "headshots": 5,
        "raw_stats_json": '{"weapon_kills":{"ak47":7,"awp":2}}',
    }

    assert _match_contribution(
        {"metric_type": "weapon_kills", "conditions_json": '{"weapon":"ak47"}'}, match
    ) == Decimal("7")
    assert _match_contribution(
        {"metric_type": "map_kills", "conditions_json": '{"map":"de_dust2"}'}, match
    ) == Decimal("12")
    assert _match_contribution(
        {"metric_type": "kd_ratio", "conditions_json": "{}"}, match
    ) == Decimal("1.50")


def test_repair_missing_contract_rewards_issues_completed_reward_once(monkeypatch):
    contract = {
        "id": 91,
        "club_id": 1,
        "guest_id": 63253,
        "title": "Охота началась",
        "reward_tokens": 3,
        "reward_bonus": 0,
    }

    class Cursor:
        def __init__(self):
            self.updated = False
            self.select_sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if sql.strip().startswith("UPDATE guest_game_contracts"):
                self.updated = True
            elif sql.strip().startswith("SELECT c.*"):
                self.select_sql = sql

        def fetchall(self):
            return [contract]

    class RepairConnection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("repair should not roll back")

        def close(self):
            return None

    connection = RepairConnection()
    awarded = []
    monkeypatch.setattr(game_contracts, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        game_contracts,
        "add_guest_token_transaction",
        lambda *args: awarded.append(args) or True,
    )

    repaired = game_contracts.repair_missing_contract_rewards(1, 63253)

    assert repaired == 1
    assert len(awarded) == 1
    assert awarded[0][4:] == ("game_contract", "91", "Награда за игровой контракт «Охота началась»")
    assert connection.cursor_instance.updated is True
    assert "source_id=CAST" not in connection.cursor_instance.select_sql
    assert connection.committed is True
