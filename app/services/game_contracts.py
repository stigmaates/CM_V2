from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction
from app.services.steam import (
    SteamError,
    fetch_dota_recent_matches,
    get_cs2_recent_matches,
    sync_cs2_match_history,
)
from app.services.wheel import add_guest_token_transaction

logger = logging.getLogger(__name__)

GAMES = {"cs2": "CS2", "dota2": "Dota 2"}
DIFFICULTIES = {"easy": "Лёгкий", "medium": "Средний", "hard": "Сложный"}
PERIOD_TYPES = {"week": "За неделю", "match": "За один матч"}
CONTRACT_DURATION = timedelta(days=7)
INGESTION_GRACE = timedelta(hours=24)
POOL_SIZE_BY_DIFFICULTY = {"easy": 2, "medium": 2, "hard": 2}

CS2_WEAPONS = (
    ("ak47", "AK-47"),
    ("m4a1", "M4A4"),
    ("m4a1_silencer", "M4A1-S"),
    ("awp", "AWP"),
    ("deagle", "Desert Eagle"),
    ("ssg08", "SSG 08"),
    ("mp9", "MP9"),
    ("mac10", "MAC-10"),
)
CS2_MAPS = (
    ("de_mirage", "Mirage"),
    ("de_inferno", "Inferno"),
    ("de_dust2", "Dust II"),
    ("de_nuke", "Nuke"),
    ("de_ancient", "Ancient"),
    ("de_anubis", "Anubis"),
    ("de_train", "Train"),
    ("de_overpass", "Overpass"),
)
DOTA_HERO_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "dota_heroes.json"
DOTA_IMAGE_BASE_URL = "https://cdn.cloudflare.steamstatic.com"
CS2_MAP_IMAGE_DIR = Path(__file__).resolve().parents[1] / "static" / "images" / "cs2" / "maps"
CS2_MAP_IMAGES = frozenset(path.stem for path in CS2_MAP_IMAGE_DIR.glob("*.jpg"))


def _load_dota_heroes() -> tuple[tuple[int, str], ...]:
    payload = json.loads(DOTA_HERO_CATALOG_PATH.read_text(encoding="utf-8"))
    heroes = tuple(
        (int(hero["id"]), str(hero["name"]))
        for hero in payload.get("heroes", [])
        if hero.get("id") and hero.get("name")
    )
    if len(heroes) < 100:
        raise RuntimeError("Каталог героев Dota 2 повреждён или неполон")
    return heroes


DOTA_HEROES = _load_dota_heroes()


def _load_dota_hero_images() -> dict[int, str]:
    payload = json.loads(DOTA_HERO_CATALOG_PATH.read_text(encoding="utf-8"))
    return {
        int(hero["id"]): str(hero["image_path"])
        for hero in payload.get("heroes", [])
        if hero.get("id") and hero.get("image_path")
    }


DOTA_HERO_IMAGES = _load_dota_hero_images()

CS2_METRIC_ARTWORK = {
    "kills": "kills",
    "headshots": "headshots",
    "wins": "victory",
    "assists": "assists",
    "mvp": "mvp",
    "kd_ratio": "kd",
    "matches_played": "warmup",
}
DOTA_METRIC_ARTWORK = {
    "kills": "combat",
    "damage": "combat",
    "assists": "support",
    "last_hits": "farm",
    "gpm": "farm",
    "xpm": "experience",
    "wins": "victory",
    "matches_played": "match",
}

GAME_METRICS = {
    "cs2": {
        "kills": "Убийства",
        "headshots": "Убийства в голову",
        "weapon_kills": "Убийства из оружия",
        "map_kills": "Убийства на карте",
        "wins": "Победы",
        "assists": "Ассисты",
        "mvp": "MVP-звёзды",
        "kd_ratio": "K/D за матч",
        "matches_played": "Сыгранные матчи",
    },
    "dota2": {
        "kills": "Убийства",
        "hero_kills": "Убийства на герое",
        "damage": "Урон по героям",
        "wins": "Победы",
        "assists": "Ассисты",
        "last_hits": "Добивания крипов",
        "gpm": "GPM за матч",
        "xpm": "XPM за матч",
        "matches_played": "Сыгранные матчи",
        "hero_played": "Матчи на герое",
    },
}

MATCH_METRICS = {"kd_ratio", "gpm", "xpm"}
CONDITION_KEYS = {
    "weapon_kills": "weapon",
    "map_kills": "map",
    "hero_kills": "hero_id",
    "hero_played": "hero_id",
}


class GameContractError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_loads(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _json_dumps(value: dict | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _decimal(value: Any, *, field: str = "Значение") -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GameContractError(f"{field} указано неверно") from exc
    if result <= 0:
        raise GameContractError(f"{field} должно быть больше нуля")
    return result.quantize(Decimal("0.01"))


def normalize_contract_template(data: dict) -> dict:
    game = str(data.get("game") or "").strip().lower()
    metric = str(data.get("metric_type") or "").strip().lower()
    difficulty = str(data.get("difficulty") or "").strip().lower()
    period_type = str(data.get("period_type") or "week").strip().lower()
    title = str(data.get("title") or "").strip()
    description = str(data.get("description_template") or data.get("description") or "").strip()
    if game not in GAMES:
        raise GameContractError("Выберите игру")
    if metric not in GAME_METRICS[game]:
        raise GameContractError("Выберите доступную метрику")
    if difficulty not in DIFFICULTIES:
        raise GameContractError("Выберите сложность")
    if period_type not in PERIOD_TYPES:
        raise GameContractError("Выберите период контракта")
    if metric in MATCH_METRICS:
        period_type = "match"
    if not title or not description:
        raise GameContractError("Заполните название и описание")

    try:
        reward_tokens = int(data.get("reward_tokens") or 0)
        reward_bonus = int(data.get("reward_bonus") or 0)
        weight = int(data.get("weight") or 100)
    except (TypeError, ValueError) as exc:
        raise GameContractError("Награда и вес должны быть целыми числами") from exc
    if reward_tokens < 0 or reward_bonus < 0:
        raise GameContractError("Награда не может быть отрицательной")
    if not 1 <= weight <= 10000:
        raise GameContractError("Вес должен быть от 1 до 10 000")

    supplied_conditions = _json_loads(data.get("conditions"))
    conditions = {}
    condition_key = CONDITION_KEYS.get(metric)
    if condition_key:
        supplied = data.get(condition_key)
        if supplied in (None, ""):
            supplied = supplied_conditions.get(condition_key)
        if supplied not in (None, ""):
            conditions[condition_key] = int(supplied) if condition_key == "hero_id" else str(supplied).strip().lower()
        if conditions.get(condition_key) in (None, "", 0):
            labels = {"weapon": "оружие", "map": "карту", "hero_id": "героя"}
            raise GameContractError(f"Укажите {labels[condition_key]} для выбранной метрики")

    return {
        "game": game,
        "title": title[:255],
        "description_template": description,
        "metric_type": metric,
        "target_value": _decimal(data.get("target_value"), field="Цель"),
        "period_type": period_type,
        "difficulty": difficulty,
        "reward_tokens": reward_tokens,
        "reward_bonus": reward_bonus,
        "weight": weight,
        "conditions_json": _json_dumps(conditions),
        "is_active": 1 if str(data.get("is_active", "1")).lower() in {"1", "true", "on", "yes"} else 0,
    }


def get_contract_templates(club_id: int, *, include_inactive: bool = True) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM game_contract_templates
                WHERE club_id = %s
                  AND (%s = 1 OR is_active = 1)
                ORDER BY game, FIELD(difficulty, 'easy', 'medium', 'hard'), title, id
                """,
                (club_id, 1 if include_inactive else 0),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    for row in rows:
        row["conditions"] = _json_loads(row.get("conditions_json"))
        row["game_label"] = GAMES.get(row.get("game"), row.get("game"))
        row["metric_label"] = GAME_METRICS.get(row.get("game"), {}).get(row.get("metric_type"), row.get("metric_type"))
        row["difficulty_label"] = DIFFICULTIES.get(row.get("difficulty"), row.get("difficulty"))
        row["period_label"] = PERIOD_TYPES.get(row.get("period_type"), row.get("period_type"))
    return rows


def get_contract_reward_settings(club_id: int) -> dict[str, dict]:
    result = {
        difficulty: {
            "difficulty": difficulty,
            "difficulty_label": label,
            "reward_tokens": 0,
            "reward_bonus": 0,
        }
        for difficulty, label in DIFFICULTIES.items()
    }
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT difficulty, reward_tokens, reward_bonus
                FROM game_contract_reward_settings
                WHERE club_id=%s
                """,
                (club_id,),
            )
            for row in cursor.fetchall():
                difficulty = str(row.get("difficulty") or "")
                if difficulty in result:
                    result[difficulty]["reward_tokens"] = int(row.get("reward_tokens") or 0)
                    result[difficulty]["reward_bonus"] = int(row.get("reward_bonus") or 0)
    finally:
        conn.close()
    return result


def get_contract_feature_settings(club_id: int) -> dict[str, bool]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT is_enabled
                FROM game_contract_settings
                WHERE club_id=%s
                """,
                (club_id,),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return {"is_enabled": bool(row and int(row.get("is_enabled") or 0))}


def is_game_contracts_enabled(club_id: int) -> bool:
    return get_contract_feature_settings(club_id)["is_enabled"]


def save_contract_reward_settings(
    club_id: int,
    values: dict[str, dict],
    *,
    is_enabled: bool | None = None,
) -> None:
    rows = []
    for difficulty in DIFFICULTIES:
        raw = values.get(difficulty) or {}
        try:
            reward_tokens = int(raw.get("reward_tokens") or 0)
            reward_bonus = int(raw.get("reward_bonus") or 0)
        except (TypeError, ValueError) as exc:
            raise GameContractError("Награда должна быть целым числом") from exc
        if reward_tokens < 0 or reward_bonus < 0:
            raise GameContractError("Награда не может быть отрицательной")
        if reward_tokens > 10000 or reward_bonus > 10_000_000:
            raise GameContractError("Указана слишком большая награда")
        rows.append((club_id, difficulty, reward_tokens, reward_bonus))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if is_enabled is not None:
                cursor.execute(
                    """
                    INSERT INTO game_contract_settings (club_id, is_enabled)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE is_enabled=VALUES(is_enabled)
                    """,
                    (club_id, 1 if is_enabled else 0),
                )
            cursor.executemany(
                """
                INSERT INTO game_contract_reward_settings
                    (club_id, difficulty, reward_tokens, reward_bonus)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    reward_tokens=VALUES(reward_tokens),
                    reward_bonus=VALUES(reward_bonus)
                """,
                rows,
            )
            cursor.execute(
                """
                UPDATE guest_game_contracts c
                JOIN game_contract_reward_settings r
                  ON r.club_id=c.club_id AND r.difficulty=c.difficulty
                SET c.reward_tokens=r.reward_tokens,
                    c.reward_bonus=r.reward_bonus,
                    c.updated_at=CURRENT_TIMESTAMP
                WHERE c.club_id=%s AND c.status='offered'
                """,
                (club_id,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _contract_rewards_for_club(cursor, club_id: int) -> dict[str, dict[str, int]]:
    rewards = {
        difficulty: {"reward_tokens": 0, "reward_bonus": 0}
        for difficulty in DIFFICULTIES
    }
    cursor.execute(
        """
        SELECT difficulty, reward_tokens, reward_bonus
        FROM game_contract_reward_settings
        WHERE club_id=%s
        """,
        (club_id,),
    )
    for row in cursor.fetchall():
        difficulty = str(row.get("difficulty") or "")
        if difficulty in rewards:
            rewards[difficulty] = {
                "reward_tokens": int(row.get("reward_tokens") or 0),
                "reward_bonus": int(row.get("reward_bonus") or 0),
            }
    return rewards


def create_contract_template(club_id: int, data: dict) -> int:
    item = normalize_contract_template(data)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO game_contract_templates (
                    club_id, game, title, description_template, metric_type, target_value,
                    period_type, difficulty, reward_tokens, reward_bonus, weight,
                    conditions_json, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (club_id, *(item[key] for key in (
                    "game", "title", "description_template", "metric_type", "target_value",
                    "period_type", "difficulty", "reward_tokens", "reward_bonus", "weight",
                    "conditions_json", "is_active",
                ))),
            )
            template_id = int(cursor.lastrowid)
        conn.commit()
        return template_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_contract_template(club_id: int, template_id: int, data: dict) -> None:
    item = normalize_contract_template(data)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE game_contract_templates
                SET game=%s, title=%s, description_template=%s, metric_type=%s,
                    target_value=%s, period_type=%s, difficulty=%s, reward_tokens=%s,
                    reward_bonus=%s, weight=%s, conditions_json=%s, is_active=%s
                WHERE id=%s AND club_id=%s
                """,
                (*(item[key] for key in (
                    "game", "title", "description_template", "metric_type", "target_value",
                    "period_type", "difficulty", "reward_tokens", "reward_bonus", "weight",
                    "conditions_json", "is_active",
                )), template_id, club_id),
            )
            if cursor.rowcount == 0:
                cursor.execute("SELECT id FROM game_contract_templates WHERE id=%s AND club_id=%s", (template_id, club_id))
                if not cursor.fetchone():
                    raise GameContractError("Шаблон контракта не найден")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def disable_contract_template(club_id: int, template_id: int) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE game_contract_templates SET is_active=0 WHERE id=%s AND club_id=%s",
                (template_id, club_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_contract_template(club_id: int, template_id: int) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM guest_game_contracts WHERE template_id=%s LIMIT 1",
                (template_id,),
            )
            if cursor.fetchone():
                raise GameContractError("Этот шаблон уже выдавался гостям — его можно только выключить")
            cursor.execute(
                "DELETE FROM game_contract_templates WHERE id=%s AND club_id=%s",
                (template_id, club_id),
            )
            if cursor.rowcount == 0:
                raise GameContractError("Шаблон контракта не найден")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _weighted_pick(items: list[dict], rng: random.Random) -> dict | None:
    if not items:
        return None
    return rng.choices(items, weights=[max(int(item.get("weight") or 1), 1) for item in items], k=1)[0]


def select_contract_templates(
    templates: list[dict], previous_ids: set[int] | None = None, *, rng: random.Random | None = None
) -> list[dict]:
    rng = rng or random.SystemRandom()
    previous_ids = previous_ids or set()
    chosen: list[dict] = []

    def pick(difficulty: str) -> dict | None:
        chosen_ids = {int(item["id"]) for item in chosen}
        metric_counts: dict[str, int] = {}
        for item in chosen:
            metric = str(item.get("metric_type") or "")
            metric_counts[metric] = metric_counts.get(metric, 0) + 1
        candidates = [
            item for item in templates
            if item.get("difficulty") == difficulty and int(item["id"]) not in chosen_ids
        ]
        preferred = [
            item for item in candidates
            if int(item["id"]) not in previous_ids and metric_counts.get(str(item.get("metric_type") or ""), 0) == 0
        ]
        if not preferred:
            preferred = [
                item for item in candidates
                if metric_counts.get(str(item.get("metric_type") or ""), 0) < 2
                and int(item["id"]) not in previous_ids
            ]
        if not preferred:
            preferred = [item for item in candidates if metric_counts.get(str(item.get("metric_type") or ""), 0) < 2]
        return _weighted_pick(preferred or candidates, rng)

    for difficulty, count in POOL_SIZE_BY_DIFFICULTY.items():
        for _ in range(count):
            item = pick(difficulty)
            if item:
                chosen.append(item)
    return chosen


def _generated_contract(
    title: str,
    description: str,
    metric_type: str,
    target_value: int | float | Decimal,
    difficulty: str,
    *,
    period_type: str = "week",
    conditions: dict | None = None,
) -> dict:
    return {
        "title": title,
        "description_template": description,
        "metric_type": metric_type,
        "target_value": Decimal(str(target_value)).quantize(Decimal("0.01")),
        "period_type": period_type,
        "difficulty": difficulty,
        # Club-level difficulty rewards are copied in immediately before persistence.
        "reward_tokens": 0,
        "reward_bonus": 0,
        "conditions_json": _json_dumps(conditions),
        "weight": 100,
    }


def _system_contract_candidates(game: str, rng: random.Random) -> dict[str, list[dict]]:
    if game == "cs2":
        weapon_code, weapon_name = rng.choice(CS2_WEAPONS)
        hard_weapon_code, hard_weapon_name = rng.choice(
            [item for item in CS2_WEAPONS if item[0] != weapon_code]
        )
        map_code, map_name = rng.choice(CS2_MAPS)
        hard_map_code, hard_map_name = rng.choice([item for item in CS2_MAPS if item[0] != map_code])
        return {
            "easy": [
                _generated_contract("Разминка", "Сыграть 1 матч", "matches_played", 1, "easy"),
                _generated_contract("Первый фраг", "Совершить 10 убийств", "kills", 10, "easy"),
                _generated_contract("Точно в цель", "Совершить 5 убийств в голову", "headshots", 5, "easy"),
                _generated_contract("Командная игра", "Сделать 5 ассистов", "assists", 5, "easy"),
                _generated_contract("Путь к победе", "Победить в 1 матче", "wins", 1, "easy"),
                _generated_contract("Звезда раунда", "Получить 2 MVP-звезды", "mvp", 2, "easy"),
            ],
            "medium": [
                _generated_contract("Серия убийств", "Совершить 25 убийств", "kills", 25, "medium"),
                _generated_contract("Охотник за головами", "Совершить 15 убийств в голову", "headshots", 15, "medium"),
                _generated_contract("Надёжный напарник", "Сделать 15 ассистов", "assists", 15, "medium"),
                _generated_contract("Игровой вечер", "Сыграть 3 матча", "matches_played", 3, "medium"),
                _generated_contract("Победная серия", "Победить в 2 матчах", "wins", 2, "medium"),
                _generated_contract(
                    f"Мастер {weapon_name}", f"Совершить 10 убийств из {weapon_name}",
                    "weapon_kills", 10, "medium", conditions={"weapon": weapon_code},
                ),
                _generated_contract(
                    f"Знаток {map_name}", f"Совершить 20 убийств на карте {map_name}",
                    "map_kills", 20, "medium", conditions={"map": map_code},
                ),
            ],
            "hard": [
                _generated_contract("Главный стрелок", "Совершить 60 убийств", "kills", 60, "hard"),
                _generated_contract("Только хедшоты", "Совершить 30 убийств в голову", "headshots", 30, "hard"),
                _generated_contract("Опора команды", "Сделать 30 ассистов", "assists", 30, "hard"),
                _generated_contract("Марафон", "Сыграть 5 матчей", "matches_played", 5, "hard"),
                _generated_contract("Победитель", "Победить в 4 матчах", "wins", 4, "hard"),
                _generated_contract(
                    f"Эксперт {hard_weapon_name}", f"Совершить 25 убийств из {hard_weapon_name}",
                    "weapon_kills", 25, "hard", conditions={"weapon": hard_weapon_code},
                ),
                _generated_contract(
                    f"Хозяин {hard_map_name}", f"Совершить 40 убийств на карте {hard_map_name}",
                    "map_kills", 40, "hard", conditions={"map": hard_map_code},
                ),
                _generated_contract("Жёсткий K/D", "Завершить матч с K/D не ниже 1,8", "kd_ratio", 1.8, "hard", period_type="match"),
            ],
        }

    (easy_hero_id, easy_hero_name), (medium_hero_id, medium_hero_name), (
        hard_hero_id,
        hard_hero_name,
    ) = rng.sample(DOTA_HEROES, k=3)
    return {
        "easy": [
            _generated_contract("Первая игра", "Сыграть 1 матч", "matches_played", 1, "easy"),
            _generated_contract("Охота началась", "Совершить 10 убийств", "kills", 10, "easy"),
            _generated_contract("Поддержка команды", "Сделать 15 ассистов", "assists", 15, "easy"),
            _generated_contract("Фарм", "Добить 100 крипов", "last_hits", 100, "easy"),
            _generated_contract("Первая победа", "Победить в 1 матче", "wins", 1, "easy"),
            _generated_contract("Урон по героям", "Нанести 25 000 урона героям", "damage", 25000, "easy"),
            _generated_contract(
                f"Знакомство с {easy_hero_name}", f"Сыграть 1 матч за {easy_hero_name}",
                "hero_played", 1, "easy", conditions={"hero_id": easy_hero_id},
            ),
        ],
        "medium": [
            _generated_contract("Серия матчей", "Сыграть 3 матча", "matches_played", 3, "medium"),
            _generated_contract("Боевой настрой", "Совершить 25 убийств", "kills", 25, "medium"),
            _generated_contract("Командный игрок", "Сделать 40 ассистов", "assists", 40, "medium"),
            _generated_contract("Уверенный фарм", "Добить 500 крипов", "last_hits", 500, "medium"),
            _generated_contract("Победная серия", "Победить в 2 матчах", "wins", 2, "medium"),
            _generated_contract("Серьёзный урон", "Нанести 75 000 урона героям", "damage", 75000, "medium"),
            _generated_contract(
                f"Практика на {medium_hero_name}", f"Сыграть 3 матча за {medium_hero_name}",
                "hero_played", 3, "medium", conditions={"hero_id": medium_hero_id},
            ),
            _generated_contract("Экономика", "Завершить матч с GPM не ниже 600", "gpm", 600, "medium", period_type="match"),
        ],
        "hard": [
            _generated_contract("Недельный марафон", "Сыграть 5 матчей", "matches_played", 5, "hard"),
            _generated_contract("Доминирование", "Совершить 50 убийств", "kills", 50, "hard"),
            _generated_contract("Идеальная поддержка", "Сделать 75 ассистов", "assists", 75, "hard"),
            _generated_contract("Король фарма", "Добить 1 000 крипов", "last_hits", 1000, "hard"),
            _generated_contract("Только победа", "Победить в 4 матчах", "wins", 4, "hard"),
            _generated_contract("Разрушительная сила", "Нанести 150 000 урона героям", "damage", 150000, "hard"),
            _generated_contract(
                f"Мастер {hard_hero_name}", f"Сыграть 5 матчей за {hard_hero_name}",
                "hero_played", 5, "hard", conditions={"hero_id": hard_hero_id},
            ),
            _generated_contract("Высокий темп", "Завершить матч с XPM не ниже 850", "xpm", 850, "hard", period_type="match"),
        ],
    }


def generate_system_contract_pool(
    game: str,
    *,
    rng: random.Random | None = None,
    excluded_signatures: set[tuple[str, str, str, str]] | None = None,
) -> list[dict]:
    """Build a personal six-contract pool without club-authored templates."""
    game = str(game or "").lower()
    if game not in GAMES:
        raise GameContractError("Неизвестная игра")
    rng = rng or random.SystemRandom()
    candidates = _system_contract_candidates(game, rng)
    excluded_signatures = excluded_signatures or set()
    selected: list[dict] = []
    metric_counts: dict[str, int] = {}

    for difficulty, required_count in POOL_SIZE_BY_DIFFICULTY.items():
        tier = [
            item for item in candidates[difficulty]
            if _contract_signature(item) not in excluded_signatures
        ]
        rng.shuffle(tier)
        for item in tier:
            metric = str(item["metric_type"])
            if metric_counts.get(metric, 0) >= 2:
                continue
            selected.append(item)
            metric_counts[metric] = metric_counts.get(metric, 0) + 1
            if sum(contract["difficulty"] == difficulty for contract in selected) == required_count:
                break

    if len(selected) != sum(POOL_SIZE_BY_DIFFICULTY.values()):
        raise GameContractError("Не удалось сформировать сбалансированный набор контрактов")
    for index, item in enumerate(selected, start=1):
        item["id"] = -index
    return selected


def _contract_signature(contract: dict) -> tuple[str, str, str, str]:
    """Stable identity used to keep a refreshed pool different from the previous one."""
    target = Decimal(str(contract.get("target_value") or 0)).quantize(Decimal("0.01"))
    conditions = contract.get("conditions_json")
    if isinstance(conditions, dict):
        conditions = _json_dumps(conditions)
    return (
        str(contract.get("metric_type") or ""),
        str(target),
        str(conditions or ""),
        str(contract.get("period_type") or "week"),
    )


def _available_games(cursor, club_id: int, guest_id: int) -> tuple[str | None, dict[str, bool]]:
    cursor.execute(
        "SELECT steam_id FROM guest_steam_accounts WHERE club_id=%s AND guest_id=%s LIMIT 1",
        (club_id, guest_id),
    )
    account = cursor.fetchone()
    if not account:
        return None, {"cs2": False, "dota2": False}
    cursor.execute(
        "SELECT id FROM guest_cs2_match_access WHERE club_id=%s AND guest_id=%s LIMIT 1",
        (club_id, guest_id),
    )
    return str(account["steam_id"]), {"cs2": bool(cursor.fetchone()), "dota2": True}


def generate_weekly_contracts(club_id: int, guest_id: int, game: str) -> list[dict]:
    game = str(game or "").lower()
    if game not in GAMES:
        raise GameContractError("Неизвестная игра")
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            steam_id, availability = _available_games(cursor, club_id, guest_id)
            if not steam_id:
                raise GameContractError("Сначала подключите Steam")
            # Locks one stable guest row so two button presses cannot create two sets.
            cursor.execute(
                "SELECT id FROM guest_steam_accounts WHERE club_id=%s AND guest_id=%s FOR UPDATE",
                (club_id, guest_id),
            )
            if not availability.get(game):
                message = "Сначала подключите историю матчей CS2" if game == "cs2" else "Матчи игры пока недоступны"
                raise GameContractError(message)
            cursor.execute(
                """
                SELECT id, status, started_at, expires_at
                FROM guest_game_contract_sets
                WHERE club_id=%s AND guest_id=%s AND game=%s
                ORDER BY id DESC LIMIT 1
                """,
                (club_id, guest_id, game),
            )
            last_set = cursor.fetchone()
            if last_set and last_set.get("status") == "selecting":
                conn.commit()
                return get_guest_contract_pool(club_id, guest_id, game)["contracts"]
            if (
                last_set
                and last_set.get("status") != "rerolled"
                and last_set["started_at"] + CONTRACT_DURATION > now
            ):
                raise GameContractError("Недельный набор этой игры уже получен")

            excluded_signatures: set[tuple[str, str, str, str]] = set()
            if last_set and last_set.get("status") == "rerolled":
                cursor.execute(
                    """
                    SELECT metric_type, target_value, conditions_json, period_type
                    FROM guest_game_contracts
                    WHERE set_id=%s
                    """,
                    (last_set["id"],),
                )
                excluded_signatures = {
                    _contract_signature(row) for row in cursor.fetchall()
                }

            selected = generate_system_contract_pool(
                game,
                excluded_signatures=excluded_signatures,
            )
            rewards = _contract_rewards_for_club(cursor, club_id)
            for contract in selected:
                contract.update(rewards[contract["difficulty"]])

            expires_at = now + CONTRACT_DURATION
            cursor.execute(
                """
                INSERT INTO guest_game_contract_sets
                    (club_id, guest_id, steam_id, game, status, started_at, expires_at)
                VALUES (%s, %s, %s, %s, 'selecting', %s, %s)
                """,
                (club_id, guest_id, steam_id, game, now, expires_at),
            )
            set_id = int(cursor.lastrowid)
            for template in selected:
                cursor.execute(
                    """
                    INSERT INTO guest_game_contracts (
                        set_id, club_id, guest_id, steam_id, game, template_id, title, description,
                        metric_type, target_value, period_type, difficulty, reward_tokens,
                        reward_bonus, conditions_json, status, started_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'offered', %s, %s)
                    """,
                    (
                        set_id, club_id, guest_id, steam_id, game, template["id"], template["title"],
                        template["description_template"], template["metric_type"], template["target_value"],
                        template["period_type"], template["difficulty"], template["reward_tokens"],
                        template["reward_bonus"], template.get("conditions_json"), now, expires_at,
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_guest_contract_pool(club_id, guest_id, game)["contracts"]


def _contract_image(row: dict) -> dict[str, str]:
    game = str(row.get("game") or "").lower()
    metric = str(row.get("metric_type") or "").lower()
    conditions = _json_loads(row.get("conditions_json"))
    searchable_text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("title", "description", "description_template")
    )

    if game == "dota2":
        if metric in {"tower_damage", "building_damage", "buildings_destroyed"} or any(
            word in searchable_text for word in ("башн", "тавер", "строен")
        ):
            return {
                "image_url": "/static/images/contracts/dota2/tower.webp",
                "image_fit": "cover",
                "image_position": "center",
            }

        try:
            hero_id = int(conditions.get("hero_id") or 0)
        except (TypeError, ValueError):
            hero_id = 0
        image_path = DOTA_HERO_IMAGES.get(hero_id)
        if not image_path:
            artwork = DOTA_METRIC_ARTWORK.get(metric, "victory")
            return {
                "image_url": f"/static/images/contracts/dota2/{artwork}.webp",
                "image_fit": "cover",
                "image_position": "center",
            }
        return {
            "image_url": f"{DOTA_IMAGE_BASE_URL}{image_path}",
            "image_fit": "cover",
            "image_position": "center",
        }

    if game == "cs2":
        map_code = str(conditions.get("map") or "").lower()
        weapon_code = str(conditions.get("weapon") or "").lower()
        known_weapons = {code for code, _name in CS2_WEAPONS}
        if metric == "weapon_kills" and weapon_code in known_weapons:
            return {
                "image_url": f"/static/images/cs2/weapons/{weapon_code}.png",
                "image_fit": "contain",
                "image_position": "right center",
            }
        if metric == "map_kills" and map_code in CS2_MAP_IMAGES:
            return {
                "image_url": f"/static/images/cs2/maps/{map_code}.jpg",
                "image_fit": "cover",
                "image_position": "center",
            }
        artwork = CS2_METRIC_ARTWORK.get(metric, "warmup")
        return {
            "image_url": f"/static/images/contracts/cs2/{artwork}.webp",
            "image_fit": "cover",
            "image_position": "center",
        }

    return {
        "image_url": "/static/images/contracts/dota2/victory.webp",
        "image_fit": "cover",
        "image_position": "center",
    }


def _serialize_pool_contract(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "title": str(row.get("title") or ""),
        "description": str(row.get("description") or ""),
        "difficulty": str(row.get("difficulty") or ""),
        "difficulty_label": DIFFICULTIES.get(row.get("difficulty"), row.get("difficulty")),
        "target_display": _format_number(row.get("target_value")),
        "reward_tokens": int(row.get("reward_tokens") or 0),
        "reward_bonus": int(row.get("reward_bonus") or 0),
        **_contract_image(row),
    }


def get_guest_contract_pool(club_id: int, guest_id: int, game: str) -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM guest_game_contract_sets
                WHERE club_id=%s AND guest_id=%s AND game=%s AND status='selecting'
                ORDER BY id DESC LIMIT 1
                """,
                (club_id, guest_id, game),
            )
            contract_set = cursor.fetchone()
            if not contract_set:
                return None
            cursor.execute(
                """
                SELECT * FROM guest_game_contracts
                WHERE set_id=%s AND status='offered'
                ORDER BY FIELD(difficulty, 'easy', 'medium', 'hard'), id
                """,
                (contract_set["id"],),
            )
            contracts = cursor.fetchall()
            rewards = _contract_rewards_for_club(cursor, club_id)
            for contract in contracts:
                contract.update(rewards[contract["difficulty"]])
    finally:
        conn.close()
    return {
        "set_id": int(contract_set["id"]),
        "game": game,
        "game_label": GAMES[game],
        "contracts": [_serialize_pool_contract(row) for row in contracts],
    }


def accept_weekly_contracts(club_id: int, guest_id: int, game: str, contract_ids: list[int]) -> list[dict]:
    game = str(game or "").lower()
    if game not in GAMES:
        raise GameContractError("Неизвестная игра")
    try:
        selected_ids = {int(value) for value in contract_ids}
    except (TypeError, ValueError) as exc:
        raise GameContractError("Выберите по одному контракту каждой сложности") from exc
    if len(selected_ids) != 3:
        raise GameContractError("Выберите ровно три контракта")

    now = _utcnow()
    expires_at = now + CONTRACT_DURATION
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, steam_id FROM guest_steam_accounts WHERE club_id=%s AND guest_id=%s FOR UPDATE",
                (club_id, guest_id),
            )
            account = cursor.fetchone()
            if not account:
                raise GameContractError("Сначала подключите Steam")
            cursor.execute(
                """
                SELECT * FROM guest_game_contract_sets
                WHERE club_id=%s AND guest_id=%s AND game=%s AND status='selecting'
                ORDER BY id DESC LIMIT 1 FOR UPDATE
                """,
                (club_id, guest_id, game),
            )
            contract_set = cursor.fetchone()
            if not contract_set:
                raise GameContractError("Пул контрактов уже выбран или недоступен")
            cursor.execute(
                "SELECT id, difficulty FROM guest_game_contracts WHERE set_id=%s AND status='offered' FOR UPDATE",
                (contract_set["id"],),
            )
            offered = cursor.fetchall()
            offered_by_id = {int(row["id"]): row for row in offered}
            if not selected_ids.issubset(offered_by_id):
                raise GameContractError("Один из выбранных контрактов больше недоступен")
            difficulties = {offered_by_id[contract_id]["difficulty"] for contract_id in selected_ids}
            if difficulties != set(POOL_SIZE_BY_DIFFICULTY):
                raise GameContractError("Выберите по одному лёгкому, среднему и сложному контракту")

            rewards = _contract_rewards_for_club(cursor, club_id)
            cursor.executemany(
                """
                UPDATE guest_game_contracts
                SET reward_tokens=%s, reward_bonus=%s, updated_at=%s
                WHERE set_id=%s AND difficulty=%s AND status='offered'
                """,
                [
                    (
                        reward["reward_tokens"], reward["reward_bonus"], now,
                        contract_set["id"], difficulty,
                    )
                    for difficulty, reward in rewards.items()
                ],
            )

            placeholders = ",".join(["%s"] * len(selected_ids))
            cursor.execute(
                f"""
                UPDATE guest_game_contracts
                SET status=IF(id IN ({placeholders}), 'active', 'declined'),
                    started_at=%s, expires_at=%s, updated_at=%s
                WHERE set_id=%s AND status='offered'
                """,
                (*sorted(selected_ids), now, expires_at, now, contract_set["id"]),
            )
            cursor.execute(
                """
                UPDATE guest_game_contract_sets
                SET status='active', started_at=%s, expires_at=%s, updated_at=%s
                WHERE id=%s
                """,
                (now, expires_at, now, contract_set["id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_guest_contracts(club_id, guest_id, game=game)


def _format_number(value: Any) -> str:
    number = Decimal(str(value or 0))
    if number == number.to_integral():
        return str(int(number))
    return str(number.quantize(Decimal("0.01"))).rstrip("0").rstrip(".").replace(".", ",")


def _remaining_label(expires_at: datetime, now: datetime) -> str:
    seconds = max(int((expires_at - now).total_seconds()), 0)
    days, seconds = divmod(seconds, 86400)
    hours = seconds // 3600
    if days:
        return f"{days} дн. {hours} ч."
    if hours:
        return f"{hours} ч."
    return f"{max(seconds // 60, 1)} мин."


def _serialize_contract(row: dict, now: datetime) -> dict:
    current = Decimal(str(row.get("current_value") or 0))
    target = Decimal(str(row.get("target_value") or 1))
    percent = min(100, max(0, int((current / target) * 100))) if target > 0 else 0
    result = dict(row)
    result.update(
        {
            "current_display": _format_number(current),
            "target_display": _format_number(target),
            "progress_percent": percent,
            "difficulty_label": DIFFICULTIES.get(row.get("difficulty"), row.get("difficulty")),
            "game_label": GAMES.get(row.get("game"), row.get("game")),
            "remaining_label": _remaining_label(row["expires_at"], now),
            "is_waiting_for_sync": row.get("status") == "active" and row["expires_at"] <= now,
            "conditions": _json_loads(row.get("conditions_json")),
        }
    )
    return result


def get_guest_contracts(club_id: int, guest_id: int, *, game: str | None = None) -> list[dict]:
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT * FROM guest_game_contracts
                WHERE club_id=%s AND guest_id=%s
                  AND status IN ('active', 'completed')
                  AND started_at >= DATE_SUB(%s, INTERVAL 8 DAY)
            """
            params: list[Any] = [club_id, guest_id, now]
            if game:
                sql += " AND game=%s"
                params.append(game)
            sql += " ORDER BY game, set_id DESC, id"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    latest_set_by_game: dict[str, int] = {}
    for row in rows:
        latest_set_by_game.setdefault(row["game"], int(row["set_id"]))
    return [_serialize_contract(row, now) for row in rows if int(row["set_id"]) == latest_set_by_game[row["game"]]]


def add_contract_refreshes(
    cursor,
    *,
    club_id: int,
    guest_id: int,
    amount: int,
) -> int:
    """Add refreshes inside an existing transaction, for example when a case is opened."""
    amount = int(amount or 0)
    if amount <= 0:
        raise GameContractError("Количество обновлений должно быть больше нуля")
    cursor.execute(
        """
        INSERT INTO guest_contract_refresh_balances
            (club_id, guest_id, balance, created_at, updated_at)
        VALUES (%s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
            balance=balance + VALUES(balance),
            updated_at=UTC_TIMESTAMP()
        """,
        (club_id, guest_id, amount),
    )
    cursor.execute(
        """
        SELECT balance FROM guest_contract_refresh_balances
        WHERE club_id=%s AND guest_id=%s
        """,
        (club_id, guest_id),
    )
    return int((cursor.fetchone() or {}).get("balance") or 0)


def get_contract_refresh_balance(club_id: int, guest_id: int) -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT balance FROM guest_contract_refresh_balances
                WHERE club_id=%s AND guest_id=%s
                """,
                (club_id, guest_id),
            )
            return int((cursor.fetchone() or {}).get("balance") or 0)
    finally:
        conn.close()


def reroll_guest_contracts(
    club_id: int,
    guest_id: int,
    game: str,
    *,
    consume_refresh: bool = True,
) -> dict:
    """Archive the latest unfinished set so the next request creates a different pool."""
    game = str(game or "").lower()
    if game not in GAMES:
        raise GameContractError("Неизвестная игра")
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, steam_id FROM guest_steam_accounts WHERE club_id=%s AND guest_id=%s FOR UPDATE",
                (club_id, guest_id),
            )
            account = cursor.fetchone()
            if not account:
                raise GameContractError("Сначала подключите Steam")

            cursor.execute(
                """
                SELECT * FROM guest_game_contract_sets
                WHERE club_id=%s AND guest_id=%s AND game=%s
                ORDER BY id DESC LIMIT 1 FOR UPDATE
                """,
                (club_id, guest_id, game),
            )
            contract_set = cursor.fetchone()
            if not contract_set or contract_set.get("status") not in {"selecting", "active"}:
                raise GameContractError("Нет текущего набора контрактов для обновления")

            cursor.execute(
                """
                SELECT COUNT(*) AS completed_count
                FROM guest_game_contracts
                WHERE set_id=%s
                  AND (status='completed' OR reward_claimed_at IS NOT NULL)
                """,
                (contract_set["id"],),
            )
            if int((cursor.fetchone() or {}).get("completed_count") or 0):
                raise GameContractError("Нельзя обновить набор с уже выполненным контрактом")

            cursor.execute(
                """
                SELECT metric_type, target_value, conditions_json, period_type
                FROM guest_game_contracts
                WHERE set_id=%s
                """,
                (contract_set["id"],),
            )
            excluded_signatures = {
                _contract_signature(row) for row in cursor.fetchall()
            }
            selected = generate_system_contract_pool(
                game,
                excluded_signatures=excluded_signatures,
            )
            rewards = _contract_rewards_for_club(cursor, club_id)
            for contract in selected:
                contract.update(rewards[contract["difficulty"]])

            remaining = None
            if consume_refresh:
                cursor.execute(
                    """
                    SELECT balance FROM guest_contract_refresh_balances
                    WHERE club_id=%s AND guest_id=%s FOR UPDATE
                    """,
                    (club_id, guest_id),
                )
                balance = int((cursor.fetchone() or {}).get("balance") or 0)
                if balance <= 0:
                    raise GameContractError("Нет доступных обновлений контрактов")
                remaining = balance - 1
                cursor.execute(
                    """
                    UPDATE guest_contract_refresh_balances
                    SET balance=%s, updated_at=%s
                    WHERE club_id=%s AND guest_id=%s
                    """,
                    (remaining, now, club_id, guest_id),
                )

            cursor.execute(
                """
                UPDATE guest_game_contracts
                SET status='rerolled', updated_at=%s
                WHERE set_id=%s AND status IN ('offered', 'active', 'declined')
                """,
                (now, contract_set["id"]),
            )
            cursor.execute(
                """
                UPDATE guest_game_contract_sets
                SET status='rerolled', finalized_at=%s, updated_at=%s
                WHERE id=%s
                """,
                (now, now, contract_set["id"]),
            )

            expires_at = now + CONTRACT_DURATION
            cursor.execute(
                """
                INSERT INTO guest_game_contract_sets
                    (club_id, guest_id, steam_id, game, status, started_at, expires_at)
                VALUES (%s, %s, %s, %s, 'selecting', %s, %s)
                """,
                (club_id, guest_id, str(account["steam_id"]), game, now, expires_at),
            )
            new_set_id = int(cursor.lastrowid)
            for template in selected:
                cursor.execute(
                    """
                    INSERT INTO guest_game_contracts (
                        set_id, club_id, guest_id, steam_id, game, template_id, title, description,
                        metric_type, target_value, period_type, difficulty, reward_tokens,
                        reward_bonus, conditions_json, status, started_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'offered', %s, %s)
                    """,
                    (
                        new_set_id, club_id, guest_id, str(account["steam_id"]), game, template["id"],
                        template["title"], template["description_template"], template["metric_type"],
                        template["target_value"], template["period_type"], template["difficulty"],
                        template["reward_tokens"], template["reward_bonus"], template.get("conditions_json"),
                        now, expires_at,
                    ),
                )
        conn.commit()
        return {
            "set_id": int(contract_set["id"]),
            "new_set_id": new_set_id,
            "game": game,
            "refreshes_remaining": remaining,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_guest_contracts_state(club_id: int, guest_id: int) -> dict:
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            steam_id, availability = _available_games(cursor, club_id, guest_id)
            cursor.execute(
                """
                SELECT s.* FROM guest_game_contract_sets s
                JOIN (
                    SELECT game, MAX(id) AS id
                    FROM guest_game_contract_sets
                    WHERE club_id=%s AND guest_id=%s GROUP BY game
                ) latest ON latest.id=s.id
                """,
                (club_id, guest_id),
            )
            sets = {row["game"]: row for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT game, last_attempt_at, last_synced_at, last_error
                FROM guest_game_sync_state
                WHERE club_id=%s AND guest_id=%s
                """,
                (club_id, guest_id),
            )
            sync_states = {row["game"]: row for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT balance FROM guest_contract_refresh_balances
                WHERE club_id=%s AND guest_id=%s
                """,
                (club_id, guest_id),
            )
            refresh_balance = int((cursor.fetchone() or {}).get("balance") or 0)
    finally:
        conn.close()
    contracts = get_guest_contracts(club_id, guest_id)
    offers = {game: get_guest_contract_pool(club_id, guest_id, game) for game in GAMES}
    by_game = {game: [] for game in GAMES}
    for contract in contracts:
        by_game[contract["game"]].append(contract)
    games = {}
    for game, label in GAMES.items():
        last_set = sets.get(game)
        offer = offers.get(game)
        next_at = (
            last_set["started_at"] + CONTRACT_DURATION
            if last_set and last_set.get("status") not in {"selecting", "rerolled"}
            else now
        )
        games[game] = {
            "key": game,
            "label": label,
            "available": bool(availability.get(game)),
            "templates_count": 6,
            "contracts": by_game[game],
            "offer": offer,
            "can_generate": bool(
                steam_id
                and availability.get(game)
                and (offer or next_at <= now)
            ),
            "next_at": next_at,
            "next_label": _remaining_label(next_at, now) if next_at > now and not offer else None,
            "sync": sync_states.get(game) or {},
            "can_refresh": bool(
                refresh_balance > 0
                and last_set
                and last_set.get("status") in {"selecting", "active"}
                and not any(contract.get("status") == "completed" for contract in by_game[game])
            ),
        }
    return {
        "steam_linked": bool(steam_id),
        "refresh_balance": refresh_balance,
        "games": games,
    }


def _upsert_match(cursor, *, club_id: int, guest_id: int, steam_id: str, game: str, match: dict) -> None:
    started_raw = match.get("started_at") if game == "dota2" else match.get("played_at")
    try:
        started_at = datetime.fromtimestamp(int(started_raw), UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return
    match_id = str(match.get("match_id") or match.get("share_code") or "").strip()
    if not match_id:
        return
    raw_stats = dict(match)
    cursor.execute(
        """
        INSERT INTO game_match_stats (
            club_id, guest_id, steam_id, game, match_id, match_started_at, map_name,
            hero_id, hero_name, kills, deaths, assists, headshots, damage, last_hits,
            gpm, xpm, mvp, won, raw_stats_json, source, parser_version
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            match_started_at=VALUES(match_started_at), map_name=VALUES(map_name),
            hero_id=VALUES(hero_id), hero_name=VALUES(hero_name), kills=VALUES(kills),
            deaths=VALUES(deaths), assists=VALUES(assists), headshots=VALUES(headshots),
            damage=VALUES(damage), last_hits=VALUES(last_hits), gpm=VALUES(gpm),
            xpm=VALUES(xpm), mvp=VALUES(mvp), won=VALUES(won),
            raw_stats_json=VALUES(raw_stats_json), source=VALUES(source),
            parser_version=VALUES(parser_version)
        """,
        (
            club_id, guest_id, steam_id, game, match_id, started_at, match.get("map_name"),
            match.get("hero_id"), match.get("hero_name"), int(match.get("kills") or 0),
            int(match.get("deaths") or 0), int(match.get("assists") or 0),
            int(match.get("headshots") or 0), int(match.get("damage") or match.get("hero_damage") or 0),
            int(match.get("last_hits") or 0), int(match.get("gpm") or 0), int(match.get("xpm") or 0),
            int(match.get("mvp") or 0), match.get("won"), _json_dumps(raw_stats),
            "opendota" if game == "dota2" else "steam_demo", match.get("parser_version"),
        ),
    )


def _match_contribution(contract: dict, match: dict) -> Decimal:
    metric = contract["metric_type"]
    conditions = _json_loads(contract.get("conditions_json"))
    raw = _json_loads(match.get("raw_stats_json"))
    if metric == "map_kills" and str(match.get("map_name") or "").lower() != str(conditions.get("map") or "").lower():
        return Decimal(0)
    if metric in {"hero_kills", "hero_played"} and int(match.get("hero_id") or 0) != int(conditions.get("hero_id") or 0):
        return Decimal(0)
    if metric == "matches_played":
        return Decimal(1)
    if metric == "wins":
        return Decimal(1 if match.get("won") else 0)
    if metric in {"kills", "headshots", "assists", "mvp", "damage", "last_hits", "gpm", "xpm"}:
        return Decimal(str(match.get(metric) or 0))
    if metric == "map_kills" or metric == "hero_kills":
        return Decimal(str(match.get("kills") or 0))
    if metric == "hero_played":
        return Decimal(1)
    if metric == "weapon_kills":
        weapon = str(conditions.get("weapon") or "").lower()
        return Decimal(str((_json_loads(raw.get("weapon_kills"))).get(weapon) or 0))
    if metric == "kd_ratio":
        kills = Decimal(str(match.get("kills") or 0))
        deaths = Decimal(str(match.get("deaths") or 0))
        return kills if deaths == 0 else (kills / deaths).quantize(Decimal("0.01"))
    return Decimal(0)


def _award_completed_contract(cursor, contract: dict) -> int:
    source_id = str(contract["id"])
    description = f"Награда за игровой контракт «{contract['title']}»"
    awarded = 0
    if int(contract.get("reward_tokens") or 0) > 0:
        awarded += int(
            add_guest_token_transaction(
                cursor, int(contract["guest_id"]), int(contract["club_id"]),
                int(contract["reward_tokens"]), "game_contract", source_id, description,
            )
        )
    if int(contract.get("reward_bonus") or 0) > 0:
        awarded += int(
            add_cm_bonus_transaction(
                cursor, int(contract["guest_id"]), int(contract["club_id"]),
                int(contract["reward_bonus"]), "game_contract", source_id, description,
            )
        )
    return awarded


def repair_missing_contract_rewards(club_id: int, guest_id: int) -> int:
    """Issue completed contract rewards missing from the ledgers, without duplicates."""
    now = _utcnow()
    repaired = 0
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.*
                FROM guest_game_contracts c
                WHERE c.club_id=%s AND c.guest_id=%s AND c.status='completed'
                  AND (c.reward_tokens > 0 OR c.reward_bonus > 0)
                  AND (c.reward_claimed_at IS NULL OR c.completed_at >= DATE_SUB(%s, INTERVAL 30 DAY))
                ORDER BY c.completed_at DESC, c.id DESC
                FOR UPDATE
                """,
                (club_id, guest_id, now),
            )
            contracts = cursor.fetchall()
            for contract in contracts:
                if _award_completed_contract(cursor, contract) > 0:
                    repaired += 1
                cursor.execute(
                    """
                    UPDATE guest_game_contracts
                    SET reward_claimed_at=COALESCE(reward_claimed_at, %s), updated_at=%s
                    WHERE id=%s
                    """,
                    (now, now, contract["id"]),
                )
        conn.commit()
        return repaired
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def evaluate_contracts_for_guest(club_id: int, guest_id: int, game: str) -> int:
    now = _utcnow()
    completed = 0
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM guest_game_contracts
                WHERE club_id=%s AND guest_id=%s AND game=%s AND status='active'
                  AND expires_at >= DATE_SUB(%s, INTERVAL 24 HOUR)
                FOR UPDATE
                """,
                (club_id, guest_id, game, now),
            )
            contracts = cursor.fetchall()
            for contract in contracts:
                cursor.execute(
                    """
                    SELECT * FROM game_match_stats
                    WHERE club_id=%s AND guest_id=%s AND game=%s
                      AND match_started_at >= %s AND match_started_at < %s
                    ORDER BY match_started_at, id
                    """,
                    (club_id, guest_id, game, contract["started_at"], contract["expires_at"]),
                )
                matches = cursor.fetchall()
                for match in matches:
                    contribution = _match_contribution(contract, match)
                    cursor.execute(
                        """
                        INSERT INTO game_contract_match_contributions
                            (contract_id, guest_id, game, match_id, contribution_value, details_json)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                            contribution_value=VALUES(contribution_value),
                            details_json=VALUES(details_json)
                        """,
                        (
                            contract["id"], guest_id, game, match["match_id"], contribution,
                            _json_dumps({"metric": contract["metric_type"], "value": str(contribution)}),
                        ),
                    )
                aggregate = "MAX" if contract["period_type"] == "match" else "SUM"
                cursor.execute(
                    f"SELECT COALESCE({aggregate}(contribution_value), 0) AS value "
                    "FROM game_contract_match_contributions WHERE contract_id=%s",
                    (contract["id"],),
                )
                new_value = Decimal(str((cursor.fetchone() or {}).get("value") or 0)).quantize(Decimal("0.01"))
                old_value = Decimal(str(contract.get("current_value") or 0)).quantize(Decimal("0.01"))
                target = Decimal(str(contract["target_value"]))
                is_completed = new_value >= target
                cursor.execute(
                    """
                    UPDATE guest_game_contracts
                    SET current_value=%s, last_checked_at=%s,
                        status=IF(%s=1, 'completed', status),
                        completed_at=IF(%s=1, COALESCE(completed_at, %s), completed_at)
                    WHERE id=%s
                    """,
                    (new_value, now, int(is_completed), int(is_completed), now, contract["id"]),
                )
                if new_value != old_value:
                    cursor.execute(
                        """
                        INSERT INTO game_contract_progress_log
                            (contract_id, guest_id, game, old_value, added_value, new_value, event_type)
                        VALUES (%s,%s,%s,%s,%s,%s,'recalculated')
                        """,
                        (contract["id"], guest_id, game, old_value, new_value - old_value, new_value),
                    )
                if is_completed and not contract.get("reward_claimed_at"):
                    _award_completed_contract(cursor, contract)
                    cursor.execute(
                        "UPDATE guest_game_contracts SET reward_claimed_at=%s WHERE id=%s AND reward_claimed_at IS NULL",
                        (now, contract["id"]),
                    )
                    completed += 1
        conn.commit()
        return completed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sync_contracts_for_guest(club_id: int, guest_id: int, game: str) -> dict:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT steam_id FROM guest_steam_accounts WHERE club_id=%s AND guest_id=%s LIMIT 1",
                (club_id, guest_id),
            )
            account = cursor.fetchone()
    finally:
        conn.close()
    if not account:
        return {"matches": 0, "completed": 0}
    steam_id = str(account["steam_id"])
    if game == "dota2":
        matches = fetch_dota_recent_matches(steam_id, limit=20).get("matches", [])
    elif game == "cs2":
        try:
            sync_cs2_match_history(club_id=club_id, guest_id=guest_id, steam_id=steam_id)
        except SteamError:
            pass
        matches = get_cs2_recent_matches(club_id=club_id, guest_id=guest_id, limit=5)
    else:
        raise GameContractError("Неизвестная игра")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            for match in matches:
                _upsert_match(
                    cursor, club_id=club_id, guest_id=guest_id, steam_id=steam_id,
                    game=game, match=match,
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"matches": len(matches), "completed": evaluate_contracts_for_guest(club_id, guest_id, game)}


def _record_sync_state(club_id: int, guest_id: int, game: str, *, error: str | None = None) -> None:
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO guest_game_sync_state
                    (club_id, guest_id, game, last_attempt_at, last_synced_at, last_error)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    last_attempt_at=VALUES(last_attempt_at),
                    last_synced_at=IF(VALUES(last_error) IS NULL, VALUES(last_synced_at), last_synced_at),
                    last_error=VALUES(last_error)
                """,
                (club_id, guest_id, game, now, None if error else now, error[:500] if error else None),
            )
        conn.commit()
    finally:
        conn.close()


def sync_contracts_for_guest(club_id: int, guest_id: int, game: str) -> dict:
    try:
        result = _sync_contracts_for_guest(club_id, guest_id, game)
    except Exception as exc:
        logger.exception("Game contract sync failed for club=%s guest=%s game=%s", club_id, guest_id, game)
        try:
            _record_sync_state(club_id, guest_id, game, error=str(exc))
        except Exception:
            logger.exception("Failed to record game contract sync error")
        raise
    _record_sync_state(club_id, guest_id, game)
    return result


def process_active_contracts() -> dict:
    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT c.club_id, c.guest_id, c.game
                FROM guest_game_contracts c
                LEFT JOIN guest_game_sync_state s
                  ON s.club_id=c.club_id AND s.guest_id=c.guest_id AND s.game=c.game
                WHERE c.status='active' AND c.expires_at >= DATE_SUB(%s, INTERVAL 24 HOUR)
                  AND (
                    c.game <> 'dota2'
                    OR s.last_attempt_at IS NULL
                    OR s.last_attempt_at < DATE_SUB(%s, INTERVAL 1 HOUR)
                  )
                ORDER BY c.club_id, c.guest_id, c.game
                """,
                (now, now),
            )
            targets = cursor.fetchall()
    finally:
        conn.close()
    result = {"guests": len(targets), "matches": 0, "completed": 0, "errors": 0}
    for target in targets:
        try:
            synced = sync_contracts_for_guest(target["club_id"], target["guest_id"], target["game"])
            result["matches"] += synced["matches"]
            result["completed"] += synced["completed"]
        except Exception:
            result["errors"] += 1
    expire_contracts(now=now)
    return result


def expire_contracts(*, now: datetime | None = None) -> int:
    now = now or _utcnow()
    cutoff = now - INGESTION_GRACE
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE guest_game_contracts
                SET status='expired', updated_at=%s
                WHERE status='active' AND expires_at < %s
                """,
                (now, cutoff),
            )
            count = cursor.rowcount
            cursor.execute(
                """
                UPDATE guest_game_contract_sets s
                SET s.status='expired', s.finalized_at=%s
                WHERE s.status='active' AND s.expires_at < %s
                  AND NOT EXISTS (
                    SELECT 1 FROM guest_game_contracts c
                    WHERE c.set_id=s.id AND c.status='active'
                  )
                """,
                (now, cutoff),
            )
        conn.commit()
        return int(count)
    finally:
        conn.close()
