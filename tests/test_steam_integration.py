from urllib.parse import parse_qs, urlparse

from flask import Flask, render_template

import app.routes.guest.main as guest_routes
import app.services.guest_management as guest_management
import app.services.steam as steam
from app.main import app
from app.routes.guest import guest_bp


class FakeResponse:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeOpenIDClient:
    def __init__(self):
        self.payload = None

    def post(self, url, data):
        assert url == steam.STEAM_OPENID_ENDPOINT
        self.payload = data
        return FakeResponse(text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")


def openid_values(steam_id="76561198000000000"):
    claimed_id = f"https://steamcommunity.com/openid/id/{steam_id}"
    return {
        "openid.mode": "id_res",
        "openid.op_endpoint": steam.STEAM_OPENID_ENDPOINT,
        "openid.claimed_id": claimed_id,
        "openid.identity": claimed_id,
        "openid.return_to": "https://stage.example/guest/steam/callback?state=abc",
        "openid.response_nonce": "nonce",
        "openid.assoc_handle": "handle",
        "openid.signed": "op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
        "openid.sig": "signature",
    }


def test_openid_redirect_uses_steam_and_callback():
    url = steam.build_openid_redirect_url(
        return_to="https://stage.example/guest/steam/callback?state=abc",
        realm="https://stage.example/",
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == steam.STEAM_OPENID_ENDPOINT
    assert params["openid.mode"] == ["checkid_setup"]
    assert params["openid.return_to"] == ["https://stage.example/guest/steam/callback?state=abc"]
    assert params["openid.realm"] == ["https://stage.example/"]


def test_openid_response_is_verified_with_steam():
    client = FakeOpenIDClient()

    steam_id = steam.verify_openid_response(openid_values(), client=client)

    assert steam_id == "76561198000000000"
    assert client.payload["openid.mode"] == "check_authentication"


def test_game_profile_returns_cs2_and_dota_hours(monkeypatch):
    def fake_api(interface, method, params, **kwargs):
        if method == "GetPlayerSummaries":
            return {
                "players": [
                    {
                        "personaname": "Игрок",
                        "profileurl": "https://steamcommunity.com/id/player/",
                        "avatarfull": "https://cdn.example/avatar.jpg",
                    }
                ]
            }
        return {
            "game_count": 2,
            "games": [
                {"appid": 730, "playtime_forever": 753, "playtime_2weeks": 90},
                {"appid": 570, "playtime_forever": 120},
            ],
        }

    monkeypatch.setattr(steam, "_steam_api_get", fake_api)

    profile = steam.fetch_game_profile("76561198000000000")

    assert profile["persona_name"] == "Игрок"
    assert profile["stats_available"] is True
    assert profile["games"] == [
        {
            "appid": 730,
            "slug": "cs2",
            "name": "Counter-Strike 2",
            "image_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg",
            "hours_total": 12.6,
            "hours_2weeks": 1.5,
        },
        {
            "appid": 570,
            "slug": "dota2",
            "name": "Dota 2",
            "image_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/570/header.jpg",
            "hours_total": 2.0,
            "hours_2weeks": 0.0,
        },
    ]


def test_dota_recent_matches_are_loaded_from_opendota(monkeypatch):
    steam_id = "76561198000000000"
    account_id = steam.steam_id_to_account_id(steam_id)

    def fake_opendota(path):
        if path == "constants/heroes":
            return {
                "46": {
                    "id": 46,
                    "name": "npc_dota_hero_templar_assassin",
                    "localized_name": "Templar Assassin",
                    "img": "/apps/dota2/images/dota_react/heroes/templar_assassin.png?",
                }
            }
        assert path == f"players/{account_id}/recentMatches"
        return [
            {
                "match_id": 987654321,
                "player_slot": 0,
                "radiant_win": True,
                "duration": 1748,
                "game_mode": 22,
                "lobby_type": 7,
                "hero_id": 46,
                "start_time": 1_789_000_000,
                "kills": 17,
                "deaths": 2,
                "assists": 16,
                "party_size": 5,
            }
        ]

    monkeypatch.setattr(steam, "_opendota_api_get", fake_opendota)
    steam._dota_hero_catalog.cache_clear()

    result = steam.fetch_dota_recent_matches(steam_id)
    steam._dota_hero_catalog.cache_clear()

    assert result == {
        "is_private": False,
        "matches": [
            {
                "match_id": "987654321",
                "hero_id": 46,
                "hero_name": "Templar Assassin",
                "hero_image_url": (
                    "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/templar_assassin.png"
                ),
                "won": True,
                "result_label": "Победа",
                "lobby_label": "Рейтинговый",
                "mode_label": "Ranked All Pick",
                "started_at": 1_789_000_000,
                "duration_seconds": 1748,
                "kills": 17,
                "deaths": 2,
                "assists": 16,
                "party_size": 5,
            }
        ],
    }


def test_dota_recent_matches_route_uses_linked_account(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        guest_routes,
        "get_linked_steam_account",
        lambda **kwargs: {"steam_id": "76561198000000000"},
    )
    monkeypatch.setattr(
        guest_routes,
        "fetch_dota_recent_matches",
        lambda steam_id: {"matches": [{"match_id": "123"}], "is_private": False},
    )
    cached = []
    monkeypatch.setattr(
        guest_routes,
        "cache_dota_recent_matches",
        lambda **kwargs: cached.append(kwargs),
    )

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.get("/guest/api/steam-dota-matches")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "matches": [{"match_id": "123"}],
        "is_private": False,
    }
    assert cached == [
        {
            "club_id": 3,
            "guest_id": 14,
            "steam_id": "76561198000000000",
            "matches": [{"match_id": "123"}],
        }
    ]


def test_dota_recent_matches_route_uses_cache_when_opendota_is_unavailable(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        guest_routes,
        "get_linked_steam_account",
        lambda **kwargs: {"steam_id": "76561198000000000"},
    )
    monkeypatch.setattr(
        guest_routes,
        "fetch_dota_recent_matches",
        lambda _steam_id: (_ for _ in ()).throw(steam.OpenDotaError("лимит")),
    )
    monkeypatch.setattr(
        guest_routes,
        "get_cached_dota_recent_matches",
        lambda **kwargs: [{"match_id": "saved"}],
    )

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.get("/guest/api/steam-dota-matches")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "matches": [{"match_id": "saved"}],
        "is_private": False,
        "warning": "OpenDota сейчас не отвечает. Показаны последние сохранённые матчи.",
    }


def test_cs2_codes_are_validated_and_auth_code_is_encrypted():
    auth_code = steam.normalize_cs2_auth_code("ABCD-EFGHI-JKLM")
    share_code = steam.normalize_cs2_share_code("CSGO-abcde-fghij-klmno-pqrst-uvwxy")

    encrypted = steam._encrypt_cs2_auth_code(auth_code)

    assert share_code == "CSGO-abcde-fghij-klmno-pqrst-uvwxy"
    assert auth_code not in encrypted
    assert steam._decrypt_cs2_auth_code(encrypted) == auth_code


def test_cs2_share_code_accepts_mixed_case_and_full_game_link():
    share_code = "CSGO-aX9KN-Lc3Nu-yzkzj-qbN6B-My6SA"

    assert steam.normalize_cs2_share_code(share_code) == share_code
    assert steam.normalize_cs2_share_code(
        f"steam://rungame/730/76561202255233023/+csgo_download_match%20{share_code}"
    ) == share_code
    assert steam.normalize_cs2_share_code(
        "CSGO-aX9KN-\u200bLc3Nu-yzkzj-\nqbN6B-My6SA"
    ) == share_code
    assert steam.normalize_cs2_share_code(
        "CSGO — aX9KN / Lc3Nu / yzkzj / qbN6B / My6SA"
    ) == share_code


def test_cs2_next_share_code_reads_steam_nested_response():
    next_code = "CSGO-bbbbb-ccccc-ddddd-eeeee-fffff"

    assert steam._next_cs2_share_code_from_payload(
        {"result": {"nextcode": next_code}}
    ) == next_code
    assert steam._next_cs2_share_code_from_payload(
        {"result": {"nextcode": "n/a"}}
    ) is None


def test_cs2_bad_map_and_generic_mode_are_refreshed():
    assert steam._cs2_match_metadata_stale(None) is True
    assert steam._cs2_match_metadata_stale(
        {"map_name": "Http", "mode_label": "Официальный матч"}
    ) is True
    assert steam._cs2_match_metadata_stale(
        {"map_name": "de_inferno", "mode_label": "Wingman"}
    ) is False


def test_cs2_sync_imports_known_match_and_walks_forward(monkeypatch):
    imported_codes = []
    advanced_codes = []
    next_codes = {
        "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa": "CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb",
        "CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb": "CSGO-ccccc-ccccc-ccccc-ccccc-ccccc",
        "CSGO-ccccc-ccccc-ccccc-ccccc-ccccc": None,
    }
    monkeypatch.setattr(
        steam,
        "get_cs2_match_access",
        lambda **kwargs: {
            "auth_code": "ABCD-EFGHI-JKLM",
            "last_share_code": "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa",
        },
    )
    monkeypatch.setattr(steam, "_cs2_match_needs_refresh", lambda **kwargs: True)
    monkeypatch.setattr(
        steam,
        "fetch_cs2_match_from_gc",
        lambda **kwargs: {"match_id": kwargs["share_code"]},
    )
    monkeypatch.setattr(
        steam,
        "_store_cs2_match",
        lambda **kwargs: imported_codes.append(kwargs["share_code"]),
    )
    monkeypatch.setattr(
        steam,
        "fetch_next_cs2_share_code",
        lambda **kwargs: next_codes[kwargs["known_code"]],
    )
    monkeypatch.setattr(
        steam,
        "_advance_cs2_match_cursor",
        lambda **kwargs: advanced_codes.append(kwargs["share_code"]),
    )

    count = steam.sync_cs2_match_history(
        club_id=3,
        guest_id=14,
        steam_id="76561198000000000",
    )

    assert count == 3
    assert imported_codes == list(next_codes)
    assert advanced_codes == list(next_codes)[1:]


def test_cs2_sync_batch_reports_one_completed_step(monkeypatch):
    monkeypatch.setattr(
        steam,
        "get_cs2_match_access",
        lambda **kwargs: {
            "auth_code": "ABCD-EFGHI-JKLM",
            "last_share_code": "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa",
        },
    )
    monkeypatch.setattr(steam, "_cs2_match_needs_refresh", lambda **kwargs: True)
    monkeypatch.setattr(
        steam,
        "fetch_cs2_match_from_gc",
        lambda **kwargs: {"match_id": kwargs["share_code"]},
    )
    monkeypatch.setattr(steam, "_store_cs2_match", lambda **kwargs: None)
    monkeypatch.setattr(
        steam,
        "fetch_next_cs2_share_code",
        lambda **kwargs: "CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb",
    )
    advanced_codes = []
    monkeypatch.setattr(
        steam,
        "_advance_cs2_match_cursor",
        lambda **kwargs: advanced_codes.append(kwargs["share_code"]),
    )

    result = steam.sync_cs2_match_history_batch(
        club_id=3,
        guest_id=14,
        steam_id="76561198000000000",
        limit=1,
    )

    assert result == {"processed": 1, "imported": 1, "has_more": True}
    assert advanced_codes == ["CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb"]


def test_cs2_match_connect_route_imports_history(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        guest_routes,
        "get_linked_steam_account",
        lambda **kwargs: {"steam_id": "76561198000000000"},
    )
    configured = []
    monkeypatch.setattr(
        guest_routes,
        "configure_cs2_match_history",
        lambda **kwargs: configured.append(kwargs) or 3,
    )
    monkeypatch.setattr(
        guest_routes,
        "get_cs2_recent_matches",
        lambda **kwargs: [{"match_id": "123", "map_label": "Mirage"}],
    )

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.post(
            "/guest/api/steam-cs2-matches/connect",
            json={
                "auth_code": "ABCD-EFGHI-JKLM",
                "share_code": "CSGO-abcde-fghij-klmno-pqrst-uvwxy",
            },
        )

    assert response.status_code == 200
    assert response.get_json()["imported"] == 3
    assert configured == [
        {
            "club_id": 3,
            "guest_id": 14,
            "steam_id": "76561198000000000",
            "auth_code": "ABCD-EFGHI-JKLM",
            "share_code": "CSGO-abcde-fghij-klmno-pqrst-uvwxy",
            "sync_limit": 0,
        }
    ]


def test_cs2_matches_route_requests_setup_when_codes_are_missing(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        guest_routes,
        "get_linked_steam_account",
        lambda **kwargs: {"steam_id": "76561198000000000"},
    )
    monkeypatch.setattr(guest_routes, "get_cs2_match_access", lambda **kwargs: None)

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.get("/guest/api/steam-cs2-matches")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "configured": False, "matches": []}


def test_cs2_matches_route_returns_single_batch_progress(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        guest_routes,
        "get_linked_steam_account",
        lambda **kwargs: {"steam_id": "76561198000000000"},
    )
    monkeypatch.setattr(guest_routes, "get_cs2_match_access", lambda **kwargs: {"last_share_code": "code"})
    calls = []
    monkeypatch.setattr(
        guest_routes,
        "sync_cs2_match_history_batch",
        lambda **kwargs: calls.append(kwargs) or {"processed": 1, "imported": 1, "has_more": True},
    )
    monkeypatch.setattr(
        guest_routes,
        "get_cs2_recent_matches",
        lambda **kwargs: [{"match_id": "123", "map_label": "Mirage"}],
    )

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.get("/guest/api/steam-cs2-matches?batch=1")

    assert response.status_code == 200
    assert response.get_json()["sync"] == {"processed": 1, "imported": 1, "has_more": True}
    assert calls == [{"club_id": 3, "guest_id": 14, "steam_id": "76561198000000000", "limit": 1}]


def test_dashboard_contract_sync_updates_active_games(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "is_rate_limited", lambda *args, **kwargs: False)
    contract = {
        "id": 91,
        "status": "active",
        "current_display": "1",
        "target_display": "3",
        "progress_percent": 33,
        "remaining_label": "6 дн. 2 ч.",
        "is_waiting_for_sync": False,
    }
    state = {
        "games": {
            "dota2": {"available": True, "contracts": [contract], "sync": {}},
            "cs2": {"available": True, "contracts": [], "sync": {}},
        }
    }
    monkeypatch.setattr(guest_routes, "get_guest_contracts_state", lambda *args: state)
    synced = []
    monkeypatch.setattr(
        guest_routes,
        "sync_contracts_for_guest",
        lambda club_id, guest_id, game: synced.append((club_id, guest_id, game)),
    )
    monkeypatch.setattr(
        guest_routes,
        "get_guest_reward_history",
        lambda **kwargs: [
            {
                "kind": "token",
                "title": "Награда за игровой контракт «Победитель»",
                "subtitle": "Баланс после: 8 жет.",
                "amount_label": "+3 жет.",
                "status_label": "начислено",
                "status_class": "issued",
                "icon": "🪙",
                "image_url": None,
                "created_at": None,
            }
        ],
    )

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.post("/guest/api/game-contracts/sync")

    assert response.status_code == 200
    assert response.get_json()["contracts"] == [contract]
    assert response.get_json()["reward_history"][0]["title"] == (
        "Награда за игровой контракт «Победитель»"
    )
    assert response.get_json()["synced_games"] == ["dota2"]
    assert synced == [(3, 14, "dota2")]


def test_steam_link_route_keeps_guest_bound_state(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes, "STEAM_PUBLIC_BASE_URL", "https://stage.example")

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(guest_logged_in=True, guest_id=14, guest_club_id=3)
        response = client.get("/guest/steam/link")
        params = parse_qs(urlparse(response.location).query)
        return_to = urlparse(params["openid.return_to"][0])
        state = parse_qs(return_to.query)["state"][0]
        with client.session_transaction() as sess:
            saved = sess["steam_link_state"]

    assert response.status_code == 302
    assert saved["guest_id"] == 14
    assert saved["club_id"] == 3
    assert saved["token"] == state
    assert saved["return_to"] == params["openid.return_to"][0]


def test_steam_callback_links_verified_account(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(guest_bp)
    monkeypatch.setattr(guest_management, "is_guest_module_banned", lambda **kwargs: False)
    monkeypatch.setattr(guest_routes.time, "time", lambda: 1_000)
    monkeypatch.setattr(guest_routes, "verify_openid_response", lambda values: "76561198000000000")
    monkeypatch.setattr(
        guest_routes,
        "fetch_player_summary",
        lambda steam_id: {"persona_name": "Игрок", "profile_url": None, "avatar_url": None},
    )
    linked = []
    monkeypatch.setattr(guest_routes, "link_steam_account", lambda **kwargs: linked.append(kwargs))
    return_to = "https://stage.example/guest/steam/callback?state=abc"

    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess.update(
                guest_logged_in=True,
                guest_id=14,
                guest_club_id=3,
                steam_link_state={
                    "token": "abc",
                    "guest_id": 14,
                    "club_id": 3,
                    "created_at": 900,
                    "return_to": return_to,
                },
            )
        response = client.get(
            "/guest/steam/callback",
            query_string={"state": "abc", "openid.mode": "id_res", "openid.return_to": return_to},
        )
        with client.session_transaction() as sess:
            assert "steam_link_state" not in sess

    assert response.status_code == 302
    assert response.location == "/guest/dashboard"
    assert linked == [
        {
            "club_id": 3,
            "guest_id": 14,
            "steam_id": "76561198000000000",
            "profile": {"persona_name": "Игрок", "profile_url": None, "avatar_url": None},
        }
    ]


def test_linked_steam_controls_render_in_guest_profile():
    with app.test_request_context("/guest/dashboard"):
        html = render_template(
            "guest/guest_dashboard.html",
            guest_name="Иван",
            profile_stats={"total_hours": 0},
            guest_missions=[],
            wheel_settings={"spin_cost": 2},
            wheel_prizes=[],
            game_mode="cases",
            cases=[],
            valuable_case_drops=[],
            token_balance=0,
            reward_history=[],
            streak_info={},
            cm_bonus_balance=0,
            cm_bonus_history=[],
            cm_bonus_redeem_history=[],
            steam_account={
                "steam_id": "76561198000000000",
                "persona_name": "Игрок",
                "profile_url": "https://steamcommunity.com/id/player/",
                "avatar_url": None,
            },
        )

    assert "Игрок" in html
    assert "Мой игровой профиль" in html
    assert 'id="steamProfileModal"' in html
    assert 'id="steamDotaMatchesModal"' in html
    assert 'id="steamCS2MatchesModal"' in html
    assert 'id="cs2MatchSetupForm"' in html
    assert "help.steampowered.com/ru/wizard/HelpWithGameIssue/" in html
    assert "Последние матчи" in html
    assert "data-steam-auth-link" in html
    assert "steam-game-cover" in html
