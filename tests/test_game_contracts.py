from decimal import Decimal
import random

import pytest

from app.services.game_contracts import (
    GameContractError,
    _match_contribution,
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
