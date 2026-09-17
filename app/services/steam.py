"""Steam OpenID linking and public game-profile data."""

from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
import pymysql

from app.config import STEAM_API_KEY
from app.core import get_db_connection

STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
STEAM_API_ROOT = "https://api.steampowered.com"
STEAM_CLAIMED_ID_RE = re.compile(r"^https?://steamcommunity\.com/openid/id/(\d{17})/?$")
SUPPORTED_GAMES = (
    {"appid": 730, "slug": "cs2", "name": "Counter-Strike 2"},
    {"appid": 570, "slug": "dota2", "name": "Dota 2"},
)


class SteamError(RuntimeError):
    """Base error for a Steam integration request."""


class SteamNotConfiguredError(SteamError):
    """The server has no Steam Web API key."""


class SteamAlreadyLinkedError(SteamError):
    """A Steam account is already linked to another guest in this club."""


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
