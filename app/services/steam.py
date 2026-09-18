"""Steam OpenID linking and public game-profile data."""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from functools import lru_cache
from urllib.parse import unquote, urlencode

import httpx
import pymysql
from cryptography.fernet import Fernet, InvalidToken

from app.config import (
    CS2_GC_BRIDGE_SECRET,
    CS2_GC_BRIDGE_URL,
    SECRET_KEY,
    STEAM_API_KEY,
)
from app.core import get_db_connection

STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
STEAM_API_ROOT = "https://api.steampowered.com"
OPENDOTA_API_ROOT = "https://api.opendota.com/api"
STEAM_CLAIMED_ID_RE = re.compile(r"^https?://steamcommunity\.com/openid/id/(\d{17})/?$")
STEAM_ID_ACCOUNT_OFFSET = 76561197960265728
DOTA_MATCH_LIMIT = 5
CS2_MATCH_LIMIT = 5
CS2_SYNC_LIMIT = 5
CS2_SHARE_CODE_RE = re.compile(r"CSGO-(?:[A-Za-z0-9]{5}-){4}[A-Za-z0-9]{5}", re.IGNORECASE)
CS2_AUTH_CODE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CS2_MAP_IMAGE_ROOT = "https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/main/images/thumbs"
CS2_MAP_LABELS = {
    "de_ancient": "Ancient",
    "de_anubis": "Anubis",
    "de_cache": "Cache",
    "de_dust2": "Dust II",
    "de_inferno": "Inferno",
    "de_mirage": "Mirage",
    "de_nuke": "Nuke",
    "de_overpass": "Overpass",
    "de_train": "Train",
    "de_vertigo": "Vertigo",
    "cs_office": "Office",
}
SUPPORTED_GAMES = (
    {
        "appid": 730,
        "slug": "cs2",
        "name": "Counter-Strike 2",
        "image_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg",
    },
    {
        "appid": 570,
        "slug": "dota2",
        "name": "Dota 2",
        "image_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/570/header.jpg",
    },
)

DOTA_LOBBY_LABELS = {
    0: "Обычный",
    1: "Тренировка",
    2: "Турнирный",
    4: "С ботами",
    7: "Рейтинговый",
    8: "1 на 1",
    9: "Боевой кубок",
}
DOTA_MODE_LABELS = {
    1: "All Pick",
    2: "Captain's Mode",
    3: "Random Draft",
    4: "Single Draft",
    5: "All Random",
    11: "Mid Only",
    16: "Captain's Draft",
    18: "Ability Draft",
    20: "All Random Deathmatch",
    21: "1v1 Mid",
    22: "Ranked All Pick",
    23: "Turbo",
}


class SteamError(RuntimeError):
    """Base error for a Steam integration request."""


class SteamNotConfiguredError(SteamError):
    """The server has no Steam Web API key."""


class SteamAlreadyLinkedError(SteamError):
    """A Steam account is already linked to another guest in this club."""


class CS2HistoryNotConfiguredError(SteamError):
    """The local CS2 Game Coordinator bridge is unavailable or not configured."""


class CS2HistoryCodeError(SteamError):
    """A guest supplied an invalid CS2 history code."""


def build_openid_redirect_url(*, return_to: str, realm: str) -> str:
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{STEAM_OPENID_ENDPOINT}?{urlencode(params)}"


def extract_steam_id(claimed_id: str) -> str | None:
    match = STEAM_CLAIMED_ID_RE.fullmatch((claimed_id or "").strip())
    return match.group(1) if match else None


def verify_openid_response(values, *, client=None) -> str:
    """Verify Steam's signed OpenID response and return its SteamID64."""
    payload = {key: value for key, value in values.items() if key.startswith("openid.")}
    claimed_id = payload.get("openid.claimed_id", "")
    steam_id = extract_steam_id(claimed_id)
    if (
        payload.get("openid.mode") != "id_res"
        or payload.get("openid.op_endpoint", "").rstrip("/") != STEAM_OPENID_ENDPOINT.rstrip("/")
        or payload.get("openid.identity") != claimed_id
        or not steam_id
    ):
        raise SteamError("Некорректный ответ Steam")

    payload["openid.mode"] = "check_authentication"
    owns_client = client is None
    client = client or httpx.Client(timeout=12.0, follow_redirects=False)
    try:
        response = client.post(STEAM_OPENID_ENDPOINT, data=payload)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SteamError("Steam временно не отвечает") from exc
    finally:
        if owns_client:
            client.close()

    valid = any(line.strip() == "is_valid:true" for line in response.text.splitlines())
    if not valid:
        raise SteamError("Steam не подтвердил вход")
    return steam_id


def _steam_api_get(
    interface: str,
    method: str,
    params: list[tuple[str, object]] | dict,
    *,
    version: str = "v0001",
):
    if not STEAM_API_KEY:
        raise SteamNotConfiguredError("На сервере не настроен STEAM_API_KEY")
    request_params = list(params.items()) if isinstance(params, dict) else list(params)
    request_params.append(("key", STEAM_API_KEY))
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.get(
                f"{STEAM_API_ROOT}/{interface}/{method}/{version}/",
                params=request_params,
            )
            response.raise_for_status()
            return response.json().get("response", {})
    except (httpx.HTTPError, ValueError) as exc:
        raise SteamError("Не удалось получить данные Steam") from exc


def fetch_player_summary(steam_id: str) -> dict | None:
    response = _steam_api_get(
        "ISteamUser",
        "GetPlayerSummaries",
        {"steamids": steam_id},
        version="v0002",
    )
    players = response.get("players") or []
    if not players:
        return None
    player = players[0]
    profile_url = str(player.get("profileurl") or "")
    avatar_url = str(player.get("avatarfull") or player.get("avatarmedium") or "")
    return {
        "steam_id": steam_id,
        "persona_name": str(player.get("personaname") or "Steam-профиль")[:255],
        "profile_url": profile_url if profile_url.startswith("https://steamcommunity.com/") else None,
        "avatar_url": avatar_url if avatar_url.startswith("https://") else None,
    }


def fetch_game_profile(steam_id: str) -> dict:
    summary = fetch_player_summary(steam_id) or {
        "steam_id": steam_id,
        "persona_name": f"Steam {steam_id}",
        "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
        "avatar_url": None,
    }
    params: list[tuple[str, object]] = [
        ("steamid", steam_id),
        ("include_appinfo", "true"),
        ("include_played_free_games", "true"),
        ("appids_filter[0]", 730),
        ("appids_filter[1]", 570),
    ]
    response = _steam_api_get("IPlayerService", "GetOwnedGames", params)
    try:
        recent_response = _steam_api_get(
            "IPlayerService",
            "GetRecentlyPlayedGames",
            {"steamid": steam_id, "count": 0},
        )
    except SteamError:
        recent_response = {}
    games_by_id = {int(game.get("appid") or 0): game for game in response.get("games") or []}
    recent_by_id = {int(game.get("appid") or 0): game for game in recent_response.get("games") or []}
    games = []
    for supported in SUPPORTED_GAMES:
        game = games_by_id.get(supported["appid"], {})
        total_minutes = int(game.get("playtime_forever") or 0)
        recent_minutes = int(
            recent_by_id.get(supported["appid"], {}).get("playtime_2weeks") or game.get("playtime_2weeks") or 0
        )
        games.append(
            {
                **supported,
                "hours_total": round(total_minutes / 60, 1),
                "hours_2weeks": round(recent_minutes / 60, 1),
            }
        )
    return {
        **summary,
        "stats_available": "game_count" in response or "total_count" in recent_response,
        "games": games,
    }


def steam_id_to_account_id(steam_id: str) -> int:
    try:
        account_id = int(steam_id) - STEAM_ID_ACCOUNT_OFFSET
    except (TypeError, ValueError) as exc:
        raise SteamError("Некорректный SteamID") from exc
    if not 0 <= account_id <= 0xFFFFFFFF:
        raise SteamError("Некорректный SteamID")
    return account_id


def _opendota_api_get(path: str):
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.get(f"{OPENDOTA_API_ROOT}/{path.lstrip('/')}")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SteamError("Не удалось получить данные OpenDota") from exc


@lru_cache(maxsize=1)
def _dota_hero_catalog() -> dict[int, dict]:
    result = _opendota_api_get("constants/heroes")
    heroes = {}
    for hero in result.values() if isinstance(result, dict) else []:
        hero_id = int(hero.get("id") or 0)
        if not hero_id:
            continue
        api_name = str(hero.get("name") or "")
        slug = api_name.removeprefix("npc_dota_hero_")
        image_path = str(hero.get("img") or "").split("?", 1)[0]
        heroes[hero_id] = {
            "name": str(hero.get("localized_name") or slug.replace("_", " ").title() or f"Герой {hero_id}"),
            "image_url": (
                f"https://cdn.cloudflare.steamstatic.com{image_path}"
                if image_path.startswith("/apps/dota2/images/")
                else None
            ),
        }
    return heroes


def fetch_dota_recent_matches(steam_id: str, *, limit: int = DOTA_MATCH_LIMIT) -> dict:
    """Return a guest's latest public Dota matches with player-level results."""
    account_id = steam_id_to_account_id(steam_id)
    safe_limit = max(1, min(int(limit), DOTA_MATCH_LIMIT))
    history = _opendota_api_get(f"players/{account_id}/recentMatches")
    history_matches = history[:safe_limit] if isinstance(history, list) else []
    if not history_matches:
        return {
            "matches": [],
            "is_private": False,
        }

    try:
        heroes = _dota_hero_catalog()
    except SteamError:
        heroes = {}
    matches = []

    for match in history_matches:
        match_id = int(match.get("match_id") or 0)
        if not match_id:
            continue
        hero_id = int(match.get("hero_id") or 0)
        hero = heroes.get(hero_id) or {"name": f"Герой #{hero_id}", "image_url": None}
        player_is_radiant = int(match.get("player_slot") or 0) < 128
        radiant_win = match.get("radiant_win")
        won = None if not isinstance(radiant_win, bool) else radiant_win == player_is_radiant
        lobby_type = int(match.get("lobby_type") or 0)
        game_mode = int(match.get("game_mode") or 0)
        matches.append(
            {
                "match_id": str(match_id),
                "hero_id": hero_id,
                "hero_name": hero["name"],
                "hero_image_url": hero["image_url"],
                "won": won,
                "result_label": "Победа" if won is True else "Поражение" if won is False else "Завершён",
                "lobby_label": DOTA_LOBBY_LABELS.get(lobby_type, "Обычный"),
                "mode_label": DOTA_MODE_LABELS.get(game_mode, "Другой режим"),
                "started_at": int(match.get("start_time") or 0),
                "duration_seconds": int(match.get("duration") or 0),
                "kills": int(match.get("kills") or 0) if "kills" in match else None,
                "deaths": int(match.get("deaths") or 0) if "deaths" in match else None,
                "assists": int(match.get("assists") or 0) if "assists" in match else None,
                "party_size": int(match.get("party_size") or 1),
            }
        )
    return {"matches": matches, "is_private": False}


def _cs2_fernet() -> Fernet:
    material = hashlib.sha256(f"cyber-bonus:cs2:{SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _encrypt_cs2_auth_code(auth_code: str) -> str:
    return _cs2_fernet().encrypt(auth_code.encode()).decode()


def _decrypt_cs2_auth_code(encrypted: str) -> str:
    try:
        return _cs2_fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise CS2HistoryCodeError("Сохранённый код CS2 больше не читается. Подключите историю заново.") from exc


def normalize_cs2_auth_code(value: str) -> str:
    code = (value or "").strip()
    if not CS2_AUTH_CODE_RE.fullmatch(code):
        raise CS2HistoryCodeError("Проверьте код авторизации истории матчей Steam")
    return code


def normalize_cs2_share_code(value: str) -> str:
    raw_value = unicodedata.normalize("NFKC", unquote((value or "").strip()))
    normalized_value = raw_value.translate(
        str.maketrans(
            {
                "\u00ad": "-",
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
            }
        )
    )
    prefixes = list(re.finditer(r"CSGO", normalized_value, re.IGNORECASE))
    if not prefixes:
        raise CS2HistoryCodeError("Не найден код CSGO-… в скопированной строке")

    for prefix in reversed(prefixes):
        code_chars = [
            char
            for char in normalized_value[prefix.end() :]
            if char.isascii() and char.isalnum()
        ][:25]
        if len(code_chars) == 25:
            compact_code = "".join(code_chars)
            groups = [compact_code[index : index + 5] for index in range(0, 25, 5)]
            return f"CSGO-{'-'.join(groups)}"
    raise CS2HistoryCodeError("Код матча после CSGO- должен содержать 25 символов")


def _next_cs2_share_code_from_payload(payload: dict) -> str | None:
    result = payload.get("result")
    if result is None and isinstance(payload.get("response"), dict):
        result = payload["response"].get("result")
    if isinstance(result, dict):
        result = result.get("nextcode") or result.get("next_code")
    result = str(result or "").strip()
    if not result or result.lower() in {"n/a", "none"}:
        return None
    return normalize_cs2_share_code(result)


def fetch_next_cs2_share_code(*, steam_id: str, auth_code: str, known_code: str) -> str | None:
    """Ask Steam for the match sharing code immediately after ``known_code``."""
    if not STEAM_API_KEY:
        raise SteamNotConfiguredError("На сервере не настроен STEAM_API_KEY")
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.get(
                f"{STEAM_API_ROOT}/ICSGOPlayers_730/GetNextMatchSharingCode/v1/",
                params={
                    "key": STEAM_API_KEY,
                    "steamid": steam_id,
                    "steamidkey": auth_code,
                    "knowncode": known_code,
                },
            )
            if response.status_code in {400, 401, 403, 404, 412}:
                raise CS2HistoryCodeError("Steam не принял коды. Проверьте код авторизации и код матча.")
            response.raise_for_status()
            payload = response.json()
    except CS2HistoryCodeError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise SteamError("Steam временно не отвечает по истории матчей") from exc

    return _next_cs2_share_code_from_payload(payload)


def fetch_cs2_match_from_gc(*, steam_id: str, share_code: str) -> dict:
    if not CS2_GC_BRIDGE_URL or not CS2_GC_BRIDGE_SECRET:
        raise CS2HistoryNotConfiguredError("Сервис матчей CS2 пока не настроен на сервере")
    try:
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            response = client.post(
                f"{CS2_GC_BRIDGE_URL}/match",
                headers={"Authorization": f"Bearer {CS2_GC_BRIDGE_SECRET}"},
                json={"steam_id": steam_id, "share_code": share_code},
            )
            if response.status_code == 503:
                raise CS2HistoryNotConfiguredError("Steam-сервис матчей CS2 ещё подключается")
            if response.status_code in {400, 404, 422}:
                raise CS2HistoryCodeError("Не удалось найти игрока в матче по этому коду")
            response.raise_for_status()
            payload = response.json()
    except (CS2HistoryNotConfiguredError, CS2HistoryCodeError):
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise CS2HistoryNotConfiguredError("Сервис матчей CS2 временно недоступен") from exc
    match = payload.get("match") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(match, dict):
        raise CS2HistoryCodeError("Steam не вернул данные матча")
    return match


def _save_cs2_match_access(*, club_id: int, guest_id: int, auth_code: str, share_code: str) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO guest_cs2_match_access (
                    club_id, guest_id, auth_code_encrypted, last_share_code
                ) VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    auth_code_encrypted = VALUES(auth_code_encrypted),
                    last_share_code = VALUES(last_share_code)
                """,
                (club_id, guest_id, _encrypt_cs2_auth_code(auth_code), share_code),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_cs2_match_access(*, club_id: int, guest_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT auth_code_encrypted, last_share_code, updated_at
                FROM guest_cs2_match_access
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                (club_id, guest_id),
            )
            row = cursor.fetchone()
        if row:
            row["auth_code"] = _decrypt_cs2_auth_code(row.pop("auth_code_encrypted"))
        return row
    finally:
        conn.close()


def _cs2_match_metadata_stale(row: dict | None) -> bool:
    if row is None:
        return True
    map_name = str(row.get("map_name") or "").strip().lower()
    mode_label = str(row.get("mode_label") or "").strip()
    return map_name in {"", "http", "https", "unknown"} or mode_label in {
        "",
        "Официальный матч",
    }


def _cs2_match_needs_refresh(*, club_id: int, guest_id: int, share_code: str) -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT map_name, mode_label
                FROM guest_cs2_matches
                WHERE club_id = %s AND guest_id = %s AND share_code = %s
                LIMIT 1
                """,
                (club_id, guest_id, share_code),
            )
            return _cs2_match_metadata_stale(cursor.fetchone())
    finally:
        conn.close()


def _store_cs2_match(*, club_id: int, guest_id: int, share_code: str, match: dict) -> None:
    fields = (
        "match_id",
        "played_at",
        "map_name",
        "mode_label",
        "result_label",
        "won",
        "team_score",
        "opponent_score",
        "duration_seconds",
        "kills",
        "deaths",
        "assists",
    )
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO guest_cs2_matches (
                    club_id, guest_id, share_code, match_id, played_at, map_name, mode_label,
                    result_label, won, team_score, opponent_score, duration_seconds, kills, deaths, assists
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    match_id = VALUES(match_id),
                    played_at = VALUES(played_at),
                    map_name = VALUES(map_name),
                    mode_label = VALUES(mode_label),
                    result_label = VALUES(result_label),
                    won = VALUES(won),
                    team_score = VALUES(team_score),
                    opponent_score = VALUES(opponent_score),
                    duration_seconds = VALUES(duration_seconds),
                    kills = VALUES(kills),
                    deaths = VALUES(deaths),
                    assists = VALUES(assists)
                """,
                (club_id, guest_id, share_code, *(match.get(field) for field in fields)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _advance_cs2_match_cursor(*, club_id: int, guest_id: int, share_code: str) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE guest_cs2_match_access
                SET last_share_code = %s
                WHERE club_id = %s AND guest_id = %s
                """,
                (share_code, club_id, guest_id),
            )
        conn.commit()
    finally:
        conn.close()


def sync_cs2_match_history(*, club_id: int, guest_id: int, steam_id: str) -> int:
    """Import the known CS2 match and move Steam's match-code cursor forward."""
    access = get_cs2_match_access(club_id=club_id, guest_id=guest_id)
    if not access:
        return 0
    auth_code = access["auth_code"]
    share_code = normalize_cs2_share_code(access["last_share_code"])
    imported = 0
    for _ in range(CS2_SYNC_LIMIT):
        if _cs2_match_needs_refresh(club_id=club_id, guest_id=guest_id, share_code=share_code):
            match = fetch_cs2_match_from_gc(steam_id=steam_id, share_code=share_code)
            _store_cs2_match(
                club_id=club_id,
                guest_id=guest_id,
                share_code=share_code,
                match=match,
            )
            imported += 1
        next_code = fetch_next_cs2_share_code(
            steam_id=steam_id,
            auth_code=auth_code,
            known_code=share_code,
        )
        if not next_code or next_code == share_code:
            break
        share_code = next_code
        _advance_cs2_match_cursor(club_id=club_id, guest_id=guest_id, share_code=share_code)
    return imported


def configure_cs2_match_history(*, club_id: int, guest_id: int, steam_id: str, auth_code: str, share_code: str) -> int:
    auth_code = normalize_cs2_auth_code(auth_code)
    share_code = normalize_cs2_share_code(share_code)
    # This call validates that the two user-provided codes belong to the linked Steam account.
    fetch_next_cs2_share_code(steam_id=steam_id, auth_code=auth_code, known_code=share_code)
    _save_cs2_match_access(
        club_id=club_id,
        guest_id=guest_id,
        auth_code=auth_code,
        share_code=share_code,
    )
    return sync_cs2_match_history(club_id=club_id, guest_id=guest_id, steam_id=steam_id)


def get_cs2_recent_matches(*, club_id: int, guest_id: int, limit: int = CS2_MATCH_LIMIT) -> list[dict]:
    safe_limit = max(1, min(int(limit), CS2_MATCH_LIMIT))
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT share_code, match_id, played_at, map_name, mode_label, result_label, won,
                       team_score, opponent_score, duration_seconds, kills, deaths, assists
                FROM guest_cs2_matches
                WHERE club_id = %s AND guest_id = %s
                ORDER BY COALESCE(played_at, 0) DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, safe_limit),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    for row in rows:
        map_name = str(row.get("map_name") or "unknown")
        safe_map = map_name if re.fullmatch(r"[a-z0-9_]+", map_name) else "unknown"
        row["map_label"] = CS2_MAP_LABELS.get(map_name, map_name.removeprefix("de_").removeprefix("cs_").title())
        row["map_image_url"] = f"{CS2_MAP_IMAGE_ROOT}/{safe_map}_1_png.png" if safe_map != "unknown" else None
        row["won"] = None if row.get("won") is None else bool(row["won"])
    return rows


def get_linked_steam_account(*, club_id: int, guest_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT steam_id, persona_name, profile_url, avatar_url, linked_at, updated_at
                FROM guest_steam_accounts
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                (club_id, guest_id),
            )
            row = cursor.fetchone()
        if row:
            row["steam_id"] = str(row["steam_id"])
        return row
    finally:
        conn.close()


def link_steam_account(*, club_id: int, guest_id: int, steam_id: str, profile: dict | None = None) -> None:
    profile = profile or {}
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT guest_id
                FROM guest_steam_accounts
                WHERE club_id = %s AND steam_id = %s
                LIMIT 1
                FOR UPDATE
                """,
                (club_id, steam_id),
            )
            existing = cursor.fetchone()
            if existing and int(existing["guest_id"]) != int(guest_id):
                raise SteamAlreadyLinkedError("Этот Steam уже привязан к другому гостю клуба")
            try:
                cursor.execute(
                    """
                    INSERT INTO guest_steam_accounts (
                        club_id, guest_id, steam_id, persona_name, profile_url, avatar_url
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        steam_id = VALUES(steam_id),
                        persona_name = VALUES(persona_name),
                        profile_url = VALUES(profile_url),
                        avatar_url = VALUES(avatar_url)
                    """,
                    (
                        club_id,
                        guest_id,
                        steam_id,
                        profile.get("persona_name"),
                        profile.get("profile_url"),
                        profile.get("avatar_url"),
                    ),
                )
            except pymysql.IntegrityError as exc:
                raise SteamAlreadyLinkedError("Этот Steam уже привязан к другому гостю клуба") from exc
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
