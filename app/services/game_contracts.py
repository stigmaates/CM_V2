from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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

    def pick(difficulties: set[str]) -> dict | None:
        chosen_ids = {int(item["id"]) for item in chosen}
        chosen_metrics = {item["metric_type"] for item in chosen}
        candidates = [
            item for item in templates
            if item.get("difficulty") in difficulties and int(item["id"]) not in chosen_ids
        ]
        preferred = [
            item for item in candidates
            if int(item["id"]) not in previous_ids and item.get("metric_type") not in chosen_metrics
        ]
        if not preferred:
            preferred = [item for item in candidates if item.get("metric_type") not in chosen_metrics]
        if not preferred:
            preferred = [item for item in candidates if int(item["id"]) not in previous_ids]
        return _weighted_pick(preferred or candidates, rng)

    for required in ({"easy"}, {"medium"}):
        item = pick(required)
        if item:
            chosen.append(item)

    roll = rng.random()
    third_difficulty = "easy" if roll < 0.30 else "medium" if roll < 0.80 else "hard"
    third = pick({third_difficulty}) or pick({"easy", "medium", "hard"})
    if third:
        chosen.append(third)
    return chosen[:3]


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
                SELECT id, started_at, expires_at
                FROM guest_game_contract_sets
                WHERE club_id=%s AND guest_id=%s AND game=%s
                ORDER BY started_at DESC, id DESC LIMIT 1
                """,
                (club_id, guest_id, game),
            )
            last_set = cursor.fetchone()
            if last_set and last_set["started_at"] + CONTRACT_DURATION > now:
                raise GameContractError("Недельный набор этой игры уже получен")

            cursor.execute(
                """
                SELECT * FROM game_contract_templates
                WHERE club_id=%s AND game=%s AND is_active=1
                ORDER BY id
                """,
                (club_id, game),
            )
            templates = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(*) AS count FROM game_match_stats
                WHERE club_id=%s AND guest_id=%s AND game=%s
                  AND match_started_at >= DATE_SUB(%s, INTERVAL 30 DAY)
                """,
                (club_id, guest_id, game, now),
            )
            has_recent_matches = int((cursor.fetchone() or {}).get("count") or 0) > 0
            if not has_recent_matches:
                templates = [template for template in templates if template.get("difficulty") != "hard"]
            if not templates:
                raise GameContractError("Владелец клуба ещё не настроил контракты для этой игры")
            previous_ids: set[int] = set()
            if last_set:
                cursor.execute("SELECT template_id FROM guest_game_contracts WHERE set_id=%s", (last_set["id"],))
                previous_ids = {int(row["template_id"]) for row in cursor.fetchall()}
            selected = select_contract_templates(templates, previous_ids)
            if not selected:
                raise GameContractError("Недостаточно активных шаблонов контрактов")

            expires_at = now + CONTRACT_DURATION
            cursor.execute(
                """
                INSERT INTO guest_game_contract_sets
                    (club_id, guest_id, steam_id, game, started_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
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
                        reward_bonus, conditions_json, started_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                SELECT game, COUNT(*) AS count
                FROM game_contract_templates
                WHERE club_id=%s AND is_active=1 GROUP BY game
                """,
                (club_id,),
            )
            pools = {row["game"]: int(row["count"]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT game, last_attempt_at, last_synced_at, last_error
                FROM guest_game_sync_state
                WHERE club_id=%s AND guest_id=%s
                """,
                (club_id, guest_id),
            )
            sync_states = {row["game"]: row for row in cursor.fetchall()}
    finally:
        conn.close()
    contracts = get_guest_contracts(club_id, guest_id)
    by_game = {game: [] for game in GAMES}
    for contract in contracts:
        by_game[contract["game"]].append(contract)
    games = {}
    for game, label in GAMES.items():
        last_set = sets.get(game)
        next_at = last_set["started_at"] + CONTRACT_DURATION if last_set else now
        games[game] = {
            "key": game,
            "label": label,
            "available": bool(availability.get(game)),
            "templates_count": pools.get(game, 0),
            "contracts": by_game[game],
            "can_generate": bool(steam_id and availability.get(game) and pools.get(game, 0) and next_at <= now),
            "next_at": next_at,
            "next_label": _remaining_label(next_at, now) if next_at > now else None,
            "sync": sync_states.get(game) or {},
        }
    return {"steam_linked": bool(steam_id), "games": games}


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


def _award_completed_contract(cursor, contract: dict) -> None:
    source_id = str(contract["id"])
    description = f"Награда за игровой контракт «{contract['title']}»"
    if int(contract.get("reward_tokens") or 0) > 0:
        add_guest_token_transaction(
            cursor, int(contract["guest_id"]), int(contract["club_id"]),
            int(contract["reward_tokens"]), "game_contract", source_id, description,
        )
    if int(contract.get("reward_bonus") or 0) > 0:
        add_cm_bonus_transaction(
            cursor, int(contract["guest_id"]), int(contract["club_id"]),
            int(contract["reward_bonus"]), "game_contract", source_id, description,
        )


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
                SELECT DISTINCT club_id, guest_id, game
                FROM guest_game_contracts
                WHERE status='active' AND expires_at >= DATE_SUB(%s, INTERVAL 24 HOUR)
                ORDER BY club_id, guest_id, game
                """,
                (now,),
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
