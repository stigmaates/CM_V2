"""FACEIT Data API integration for a guest's recent CS2 matches."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.config import FACEIT_API_KEY

FACEIT_API_ROOT = "https://open.faceit.com/data/v4"
FACEIT_MATCH_LIMIT = 5


class FaceitError(RuntimeError):
    """Base error for FACEIT requests."""


class FaceitNotConfiguredError(FaceitError):
    """The server has no FACEIT Data API key."""


def _faceit_api_get(path: str, *, params: dict | None = None, client=None):
    if not FACEIT_API_KEY:
        raise FaceitNotConfiguredError("На сервере не настроен FACEIT_API_KEY")

    owns_client = client is None
    client = client or httpx.Client(timeout=12.0, follow_redirects=False)
    try:
        response = client.get(
            f"{FACEIT_API_ROOT}/{path.lstrip('/')}",
            params=params,
            headers={"Authorization": f"Bearer {FACEIT_API_KEY}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise FaceitError("Не удалось получить данные FACEIT") from exc
    finally:
        if owns_client:
            client.close()


def _safe_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _match_stat_value(stats: dict, key: str):
    """Read FACEIT game stats while tolerating historical key casing changes."""
    if key in stats:
        return stats[key]
    wanted = key.casefold().replace("_", " ")
    for candidate, value in stats.items():
        if str(candidate).casefold().replace("_", " ") == wanted:
            return value
    return None


def _map_label(map_name: str | None) -> str:
    value = str(map_name or "").strip()
    if not value:
        return "Карта не указана"
    return value.removeprefix("de_").replace("_", " ").title()


def _safe_faceit_url(value: object) -> str | None:
    url = str(value or "").strip().replace("{lang}", "ru")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and (host == "faceit.com" or host.endswith(".faceit.com")):
        return url
    return None


def _safe_faceit_image_url(value: object) -> str | None:
    url = str(value or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = host == "faceit-cdn.net" or host.endswith(".faceit-cdn.net")
    return url if parsed.scheme == "https" and allowed else None


def _extract_map_image(match_details: dict | None, map_name: str | None) -> str | None:
    voting_map = ((match_details or {}).get("voting") or {}).get("map") or {}
    entities = voting_map.get("entities") or []
    picked = voting_map.get("pick") or []
    picked_names = {str(value).casefold() for value in picked}
    wanted = str(map_name or "").casefold()

    candidates = []
    for entity in entities if isinstance(entities, list) else []:
        names = {
            str(entity.get("name") or "").casefold(),
            str(entity.get("class_name") or "").casefold(),
            str(entity.get("game_map_id") or "").casefold(),
        }
        if wanted and wanted in names:
            candidates.insert(0, entity)
        elif picked_names.intersection(names):
            candidates.insert(0, entity)
        else:
            candidates.append(entity)
    for entity in candidates:
        image_url = _safe_faceit_image_url(entity.get("image_lg") or entity.get("image_sm"))
        if image_url:
            return image_url
    return None


def _player_faction(match: dict, player_id: str) -> str | None:
    teams = match.get("teams") or {}
    for faction, team in teams.items() if isinstance(teams, dict) else []:
        players = team.get("players") or []
        if any(str(player.get("player_id") or "") == player_id for player in players):
            return str(faction)
    return None


def _result_label(match: dict, stats: dict, player_id: str) -> tuple[bool | None, str]:
    stat_result = _safe_int(_match_stat_value(stats, "Result"))
    if stat_result in {0, 1}:
        won = stat_result == 1
        return won, "Победа" if won else "Поражение"

    winner = str(((match.get("results") or {}).get("winner") or ""))
    faction = _player_faction(match, player_id)
    if winner and faction:
        won = winner == faction
        return won, "Победа" if won else "Поражение"
    return None, "Завершён"


def fetch_faceit_recent_matches(steam_id: str, *, limit: int = FACEIT_MATCH_LIMIT) -> dict:
    """Return the latest FACEIT CS2 matches for the linked SteamID64."""
    safe_limit = max(1, min(int(limit), FACEIT_MATCH_LIMIT))
    with httpx.Client(timeout=12.0, follow_redirects=False) as client:
        player = _faceit_api_get(
            "players",
            params={"game": "cs2", "game_player_id": str(steam_id)},
            client=client,
        )
        if not player:
            return {
                "faceit_profile_found": False,
                "faceit_profile_url": None,
                "faceit_nickname": None,
                "matches": [],
            }

        player_id = str(player.get("player_id") or "")
        if not player_id:
            raise FaceitError("FACEIT вернул профиль без player_id")

        history = _faceit_api_get(
            f"players/{player_id}/history",
            params={"game": "cs2", "offset": 0, "limit": safe_limit},
            client=client,
        ) or {}
        recent_stats = _faceit_api_get(
            f"players/{player_id}/games/cs2/stats",
            params={"offset": 0, "limit": max(safe_limit, 20)},
            client=client,
        ) or {}

        stats_by_match_id = {}
        for item in recent_stats.get("items") or []:
            stats = item.get("stats") or {}
            match_id = str(_match_stat_value(stats, "Match Id") or "")
            if match_id:
                stats_by_match_id[match_id] = stats

        matches = []
        for match in (history.get("items") or [])[:safe_limit]:
            match_id = str(match.get("match_id") or "")
            if not match_id:
                continue
            stats = stats_by_match_id.get(match_id, {})
            map_name = str(_match_stat_value(stats, "Map") or "").strip() or None
            details = _faceit_api_get(f"matches/{match_id}", client=client) or {}
            if not map_name:
                picked = ((((details.get("voting") or {}).get("map") or {}).get("pick")) or [])
                map_name = str(picked[0]) if picked else None

            won, result_label = _result_label(match, stats, player_id)
            competition = str(match.get("competition_name") or "").strip()
            game_mode = str(match.get("game_mode") or match.get("match_type") or "").strip()
            type_label = competition or "FACEIT"
            type_detail = game_mode.upper() if game_mode else "CS2"

            matches.append(
                {
                    "match_id": match_id,
                    "map_name": map_name,
                    "map_label": _map_label(map_name),
                    "map_image_url": _extract_map_image(details, map_name),
                    "won": won,
                    "result_label": result_label,
                    "type_label": type_label,
                    "type_detail": type_detail,
                    "finished_at": _safe_int(match.get("finished_at")),
                    "kills": _safe_int(_match_stat_value(stats, "Kills")),
                    "deaths": _safe_int(_match_stat_value(stats, "Deaths")),
                    "assists": _safe_int(_match_stat_value(stats, "Assists")),
                    "match_url": _safe_faceit_url(match.get("faceit_url")),
                }
            )

    return {
        "faceit_profile_found": True,
        "faceit_profile_url": _safe_faceit_url(player.get("faceit_url")),
        "faceit_nickname": str(player.get("nickname") or "FACEIT")[:255],
        "matches": matches,
    }
