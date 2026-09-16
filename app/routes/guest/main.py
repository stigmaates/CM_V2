import secrets
import time
from datetime import datetime
from urllib.parse import quote, quote_plus

from flask import after_this_request, current_app, flash, redirect, render_template, request, session, url_for

from app.config import BOT_USERNAME, STEAM_PUBLIC_BASE_URL
from app.core import guest_required
from app.services.audit import record_audit_event
from app.services.cases import (
    get_cases,
    get_game_mode,
    get_valuable_case_drops,
    open_case,
    serialize_case,
)
from app.services.cm_bonuses import (
    get_cm_bonus_balance,
    get_cm_bonus_history,
    get_cm_bonus_redeem_history,
    redeem_cm_bonuses,
)
from app.services.guest_auth import (
    create_guest_login_token,
    get_guest_by_id,
    get_guest_login_club,
    get_guest_login_token,
)
from app.services.guest_rewards import get_guest_reward_history
from app.services.game_contracts import GameContractError, generate_weekly_contracts, get_guest_contracts_state
from app.services.missions import get_guest_missions_with_progress
from app.services.prize_claims import get_prize_claim_by_spin_id, serialize_prize_claim
from app.services.rate_limit import client_ip, is_rate_limited
from app.services.steam import (
    CS2HistoryCodeError,
    CS2HistoryNotConfiguredError,
    SteamAlreadyLinkedError,
    SteamError,
    SteamNotConfiguredError,
    build_openid_redirect_url,
    configure_cs2_match_history,
    fetch_dota_recent_matches,
    fetch_game_profile,
    fetch_player_summary,
    get_cs2_match_access,
    get_cs2_recent_matches,
    get_linked_steam_account,
    link_steam_account,
    sync_cs2_match_history,
    sync_cs2_match_history_batch,
    verify_openid_response,
)
from app.services.wheel import (
    get_guest_profile_stats,
    get_guest_streak_info,
    get_guest_tokens,
    get_wheel_prizes,
    get_wheel_settings,
    save_guest_wheel_spin,
    serialize_wheel_prize,
    sync_guest_wheel_tokens,
)

from . import guest_bp


def _clear_guest_session():
    session.pop("guest_id", None)
    session.pop("guest_club_id", None)
    session.pop("guest_name", None)
    session.pop("guest_telegram_id", None)
    session.pop("guest_logged_in", None)
    session.pop("guest_test_mode", None)
    session.pop("guest_test_label", None)
    session.pop("guest_test_source", None)
    session.pop("guest_test_return_label", None)


def _disable_login_cache():
    @after_this_request
    def add_no_store_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def _steam_public_origin() -> str:
    if STEAM_PUBLIC_BASE_URL:
        return STEAM_PUBLIC_BASE_URL
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.scheme
    return f"{scheme}://{request.host}".rstrip("/")


@guest_bp.route("/dashboard")
@guest_required
def dashboard():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        flash("Гость не найден", "error")
        return redirect(url_for("guest.login"))

    missions = sync_guest_wheel_tokens(guest_id=guest["guest_id"], club_id=guest["club_id"])
    profile_stats = get_guest_profile_stats(guest_id=guest["guest_id"], club_id=guest["club_id"])
    wheel_settings = get_wheel_settings(guest["club_id"])
    wheel_prizes = [serialize_wheel_prize(p) for p in get_wheel_prizes(guest["club_id"])]
    game_mode = get_game_mode(guest["club_id"])
    cases = [serialize_case(c) for c in get_cases(guest["club_id"])]
    show_only_own_valuable_drops = bool((wheel_settings or {}).get("show_only_own_valuable_drops"))
    valuable_case_drops = get_valuable_case_drops(
        limit=24,
        days=90,
        club_id=guest["club_id"] if show_only_own_valuable_drops else None,
    )
    token_balance = get_guest_tokens(guest_id=guest["guest_id"], club_id=guest["club_id"], sync=False)
    reward_history = get_guest_reward_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=12)
    streak_info = get_guest_streak_info(guest_id=guest["guest_id"], club_id=guest["club_id"])
    cm_bonus_balance = get_cm_bonus_balance(guest_id=guest["guest_id"], club_id=guest["club_id"])
    cm_bonus_history = get_cm_bonus_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=10)
    cm_bonus_redeem_history = get_cm_bonus_redeem_history(
        guest_id=guest["guest_id"], club_id=guest["club_id"], limit=30
    )
    steam_account = get_linked_steam_account(club_id=guest["club_id"], guest_id=guest["guest_id"])
    try:
        game_contracts_state = get_guest_contracts_state(guest["club_id"], guest["guest_id"])
    except Exception:
        current_app.logger.exception("Failed to load game contracts for guest %s", guest["guest_id"])
        game_contracts_state = {
            "steam_linked": bool(steam_account),
            "games": {
                "cs2": {"key": "cs2", "label": "CS2", "available": False, "contracts": [], "can_generate": False},
                "dota2": {"key": "dota2", "label": "Dota 2", "available": bool(steam_account), "contracts": [], "can_generate": False},
            },
        }

    return render_template(
        "guest/guest_dashboard.html",
        guest_name=session.get("guest_name"),
        guest_id=session.get("guest_id"),
        missions=missions,
        guest_missions=missions,
        profile_stats=profile_stats,
        wheel_settings=wheel_settings,
        wheel_prizes=wheel_prizes,
        game_mode=game_mode,
        cases=cases,
        valuable_case_drops=valuable_case_drops,
        token_balance=token_balance,
        reward_history=reward_history,
        streak_info=streak_info,
        cm_bonus_balance=cm_bonus_balance,
        cm_bonus_history=cm_bonus_history,
        cm_bonus_redeem_history=cm_bonus_redeem_history,
        steam_account=steam_account,
        game_contracts_state=game_contracts_state,
    )


@guest_bp.route("/contracts/<game>/generate", methods=["POST"])
@guest_required
def generate_game_contracts(game: str):
    club_id = int(session["guest_club_id"])
    guest_id = int(session["guest_id"])
    if is_rate_limited(f"guest.game_contracts:{club_id}:{guest_id}:{game}", limit=4, window_seconds=60):
        flash("Слишком много попыток. Подождите минуту.", "error")
        return redirect(url_for("guest.dashboard") + "#game-contracts")
    try:
        contracts = generate_weekly_contracts(club_id, guest_id, game)
        record_audit_event(
            action="guest.game_contracts.generate",
            club_id=club_id,
            entity_type="guest",
            entity_id=guest_id,
            details={"game": game, "contracts_count": len(contracts)},
        )
        flash("Недельные игровые контракты получены", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    except Exception:
        current_app.logger.exception("Failed to generate game contracts")
        flash("Не удалось получить контракты. Попробуйте позже.", "error")
    return redirect(url_for("guest.dashboard") + "#game-contracts")


@guest_bp.route("/steam/link")
@guest_required
def steam_link():
    guest_id = int(session["guest_id"])
    club_id = int(session["guest_club_id"])
    if is_rate_limited(f"guest.steam_link:{club_id}:{guest_id}", limit=10, window_seconds=60):
        flash("Слишком много попыток входа через Steam. Подождите минуту.", "error")
        return redirect(url_for("guest.dashboard"))
    state = secrets.token_urlsafe(24)
    origin = _steam_public_origin()
    callback_path = url_for("guest.steam_callback")
    return_to = f"{origin}{callback_path}?state={quote(state, safe='')}"
    session["steam_link_state"] = {
        "token": state,
        "guest_id": guest_id,
        "club_id": club_id,
        "created_at": int(time.time()),
        "return_to": return_to,
    }
    return redirect(build_openid_redirect_url(return_to=return_to, realm=f"{origin}/"))


@guest_bp.route("/steam/callback")
@guest_required
def steam_callback():
    expected = session.pop("steam_link_state", None) or {}
    supplied_state = request.args.get("state", "")
    state_age = int(time.time()) - int(expected.get("created_at") or 0)
    state_is_valid = (
        expected.get("token")
        and secrets.compare_digest(str(expected["token"]), supplied_state)
        and int(expected.get("guest_id") or 0) == int(session.get("guest_id") or 0)
        and int(expected.get("club_id") or 0) == int(session.get("guest_club_id") or 0)
        and 0 <= state_age <= 600
    )
    if not state_is_valid:
        flash("Не удалось подтвердить запрос на привязку Steam. Попробуйте ещё раз.", "error")
        return redirect(url_for("guest.dashboard"))
    if request.args.get("openid.mode") == "cancel":
        flash("Вход через Steam отменён", "error")
        return redirect(url_for("guest.dashboard"))
    if request.args.get("openid.return_to") != expected.get("return_to"):
        flash("Steam вернул ответ для другого адреса. Попробуйте ещё раз.", "error")
        return redirect(url_for("guest.dashboard"))

    try:
        steam_id = verify_openid_response(request.args.to_dict(flat=True))
        try:
            profile = fetch_player_summary(steam_id)
        except SteamError:
            profile = None
        link_steam_account(
            club_id=int(session["guest_club_id"]),
            guest_id=int(session["guest_id"]),
            steam_id=steam_id,
            profile=profile,
        )
    except SteamAlreadyLinkedError as exc:
        flash(str(exc), "error")
    except SteamError as exc:
        flash(str(exc), "error")
    else:
        flash("Steam-аккаунт успешно привязан", "success")
    return redirect(url_for("guest.dashboard"))


@guest_bp.route("/api/steam-profile")
@guest_required
def api_steam_profile():
    club_id = int(session["guest_club_id"])
    guest_id = int(session["guest_id"])
    if is_rate_limited(f"guest.steam_profile:{club_id}:{guest_id}", limit=10, window_seconds=60):
        return {
            "ok": False,
            "error": "rate_limited",
            "message": "Слишком много запросов. Подождите минуту.",
        }, 429
    account = get_linked_steam_account(
        club_id=club_id,
        guest_id=guest_id,
    )
    if not account:
        return {"ok": False, "error": "steam_not_linked", "message": "Steam-аккаунт не привязан"}, 404
    try:
        profile = fetch_game_profile(account["steam_id"])
        link_steam_account(
            club_id=club_id,
            guest_id=guest_id,
            steam_id=account["steam_id"],
            profile=profile,
        )
    except SteamNotConfiguredError:
        return {
            "ok": False,
            "error": "steam_not_configured",
            "message": "Статистика Steam пока не настроена на сервере",
        }, 503
    except SteamError:
        return {
            "ok": False,
            "error": "steam_unavailable",
            "message": "Steam временно не отвечает. Попробуйте позже.",
        }, 502
    return {"ok": True, "profile": profile}


@guest_bp.route("/api/steam-dota-matches")
@guest_required
def api_steam_dota_matches():
    club_id = int(session["guest_club_id"])
    guest_id = int(session["guest_id"])
    if is_rate_limited(f"guest.steam_dota_matches:{club_id}:{guest_id}", limit=6, window_seconds=60):
        return {
            "ok": False,
            "error": "rate_limited",
            "message": "Слишком много запросов. Подождите минуту.",
        }, 429
    account = get_linked_steam_account(club_id=club_id, guest_id=guest_id)
    if not account:
        return {"ok": False, "error": "steam_not_linked", "message": "Steam-аккаунт не привязан"}, 404
    try:
        result = fetch_dota_recent_matches(account["steam_id"])
    except SteamNotConfiguredError:
        return {
            "ok": False,
            "error": "steam_not_configured",
            "message": "Статистика Steam пока не настроена на сервере",
        }, 503
    except SteamError:
        return {
            "ok": False,
            "error": "steam_unavailable",
            "message": "Не удалось получить матчи Dota 2. Попробуйте позже.",
        }, 502
    return {"ok": True, **result}


@guest_bp.route("/api/steam-cs2-matches")
@guest_required
def api_steam_cs2_matches():
    club_id = int(session["guest_club_id"])
    guest_id = int(session["guest_id"])
    if is_rate_limited(f"guest.steam_cs2_matches:{club_id}:{guest_id}", limit=10, window_seconds=60):
        return {
            "ok": False,
            "error": "rate_limited",
            "message": "Слишком много запросов. Подождите минуту.",
        }, 429
    account = get_linked_steam_account(club_id=club_id, guest_id=guest_id)
    if not account:
        return {
            "ok": False,
            "error": "steam_not_linked",
            "message": "Steam-аккаунт не привязан",
        }, 404
    access = get_cs2_match_access(club_id=club_id, guest_id=guest_id)
    if not access:
        return {"ok": True, "configured": False, "matches": []}

    warning = None
    sync_state = None
    try:
        if request.args.get("batch") == "1":
            sync_state = sync_cs2_match_history_batch(
                club_id=club_id,
                guest_id=guest_id,
                steam_id=account["steam_id"],
                limit=1,
            )
        else:
            sync_cs2_match_history(
                club_id=club_id,
                guest_id=guest_id,
                steam_id=account["steam_id"],
            )
    except (SteamError, CS2HistoryNotConfiguredError, CS2HistoryCodeError) as exc:
        warning = str(exc)
    matches = get_cs2_recent_matches(club_id=club_id, guest_id=guest_id)
    return {
        "ok": True,
        "configured": True,
        "matches": matches,
        "warning": warning,
        "sync": sync_state,
    }


@guest_bp.route("/api/steam-cs2-matches/connect", methods=["POST"])
@guest_required
def api_steam_cs2_matches_connect():
    club_id = int(session["guest_club_id"])
    guest_id = int(session["guest_id"])
    if is_rate_limited(f"guest.steam_cs2_connect:{club_id}:{guest_id}", limit=5, window_seconds=300):
        return {
            "ok": False,
            "error": "rate_limited",
            "message": "Слишком много попыток. Подождите несколько минут.",
        }, 429
    account = get_linked_steam_account(club_id=club_id, guest_id=guest_id)
    if not account:
        return {
            "ok": False,
            "error": "steam_not_linked",
            "message": "Steam-аккаунт не привязан",
        }, 404
    payload = request.get_json(silent=True) or {}
    try:
        imported = configure_cs2_match_history(
            club_id=club_id,
            guest_id=guest_id,
            steam_id=account["steam_id"],
            auth_code=str(payload.get("auth_code") or ""),
            share_code=str(payload.get("share_code") or ""),
            sync_limit=0,
        )
    except CS2HistoryCodeError as exc:
        return {"ok": False, "error": "invalid_codes", "message": str(exc)}, 400
    except SteamNotConfiguredError:
        return {
            "ok": False,
            "error": "steam_not_configured",
            "message": "Статистика Steam пока не настроена на сервере",
        }, 503
    except CS2HistoryNotConfiguredError as exc:
        return {
            "ok": False,
            "error": "gc_unavailable",
            "message": f"Коды сохранены. {exc}",
            "setup_saved": True,
        }, 503
    except SteamError as exc:
        return {"ok": False, "error": "steam_unavailable", "message": str(exc)}, 502
    return {
        "ok": True,
        "configured": True,
        "imported": imported,
        "matches": get_cs2_recent_matches(club_id=club_id, guest_id=guest_id),
    }


@guest_bp.route("/check-login")
def check_login():
    _disable_login_cache()
    token = request.args.get("token", "").strip()
    if not token:
        return {"ok": False, "error": "token_required"}, 400
    ip = client_ip()
    token_prefix = token[:12]
    if is_rate_limited(f"guest.check_login:{ip}:{token_prefix}", limit=30, window_seconds=60):
        return {"ok": False, "error": "rate_limited"}, 429

    token_row = get_guest_login_token(token)
    if not token_row:
        return {"ok": False, "error": "token_not_found"}, 404

    now = datetime.utcnow()
    expires_at = token_row["expires_at"]
    if expires_at and expires_at < now:
        return {"ok": False, "status": "expired"}

    if not token_row["is_confirmed"]:
        return {"ok": True, "status": "pending"}

    guest_id = token_row["guest_id"]
    if not guest_id:
        return {"ok": False, "error": "guest_not_set"}, 500

    guest = get_guest_by_id(guest_id, token_row.get("club_id"))
    if not guest:
        return {"ok": False, "error": "guest_not_found"}, 404

    session["guest_id"] = guest["guest_id"]
    session["guest_club_id"] = guest["club_id"]
    session["guest_name"] = guest.get("fio")
    session["guest_telegram_id"] = guest.get("telegram_id")
    session["guest_logged_in"] = True

    return {"ok": True, "status": "confirmed", "redirect_url": url_for("guest.dashboard")}


@guest_bp.route("/login")
def login():
    _disable_login_cache()
    bot_username = BOT_USERNAME.lstrip("@")
    requested_club_id = request.args.get("club_id", type=int) or session.get("club_id")
    club = get_guest_login_club(requested_club_id)
    if not club:
        return render_template("guest/guest_login_error.html"), 400

    current_guest_club_id = session.get("guest_club_id")
    if current_guest_club_id is not None and int(current_guest_club_id) != int(club["club_id"]):
        _clear_guest_session()
    elif session.get("guest_logged_in") and session.get("guest_id"):
        return redirect(url_for("guest.dashboard"))

    token = create_guest_login_token(int(club["club_id"]))
    start_payload = f"login_{token}"
    bot_link = f"https://t.me/{bot_username}?start={start_payload}"
    telegram_link = f"tg://resolve?domain={bot_username}&start={start_payload}"
    qr_link = quote_plus(telegram_link)
    return render_template(
        "guest/guest_login.html",
        bot_link=bot_link,
        telegram_link=telegram_link,
        qr_link=qr_link,
        token=token,
        club=club,
    )


@guest_bp.route("/api/tokens")
@guest_required
def api_guest_tokens():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    club_id = guest["club_id"]
    settings = get_wheel_settings(club_id)

    if not settings:
        return {
            "tokens": 0,
            "is_enabled": False,
            "spin_cost": 2,
            "message": "Колесо фортуны пока не настроено для этого клуба",
        }

    tokens = get_guest_tokens(guest_id, club_id)

    return {
        "tokens": tokens,
        "is_enabled": bool(settings.get("is_enabled")),
        "spin_cost": settings.get("spin_cost", 2),
        "tokens_start_date": (
            settings.get("tokens_start_date").isoformat() if settings.get("tokens_start_date") else None
        ),
    }


@guest_bp.route("/api/wheel/spin", methods=["POST"])
@guest_required
def api_wheel_spin():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    club_id = guest["club_id"]
    settings = get_wheel_settings(club_id)
    if not settings:
        return {"error": "wheel_not_configured"}, 400

    if not settings.get("is_enabled"):
        return {"error": "wheel_disabled"}, 400

    spin_cost = int(settings.get("spin_cost") or 2)
    if spin_cost <= 0:
        spin_cost = 2

    tokens = get_guest_tokens(guest_id, club_id)
    if tokens < spin_cost:
        return {"error": "no_tokens"}, 400

    prizes = get_wheel_prizes(club_id)
    if not prizes:
        return {"error": "no_prizes"}, 400

    try:
        spin_id, prize = save_guest_wheel_spin(
            guest_id=guest_id,
            club_id=club_id,
            spent_tokens=spin_cost,
            test_mode=bool(session.get("guest_test_mode")),
            return_prize=True,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    tokens_after = get_guest_tokens(guest_id, club_id)

    claim = get_prize_claim_by_spin_id(spin_id)

    return {
        "ok": True,
        "spin_id": spin_id,
        "tokens_after": tokens_after,
        "prize": serialize_wheel_prize(prize),
        "claim": serialize_prize_claim(claim),
    }


@guest_bp.route("/api/cases")
@guest_required
def api_cases():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    club_id = guest["club_id"]
    return {
        "game_mode": get_game_mode(club_id),
        "cases": [serialize_case(c) for c in get_cases(club_id)],
        "tokens": get_guest_tokens(guest_id, club_id),
    }


@guest_bp.route("/api/cases/<int:case_id>/open", methods=["POST"])
@guest_required
def api_case_open(case_id):
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    club_id = guest["club_id"]

    if get_game_mode(club_id) != "cases":
        return {"error": "cases_disabled"}, 400

    try:
        result = open_case(
            guest_id=guest_id,
            club_id=club_id,
            case_id=case_id,
            test_mode=bool(session.get("guest_test_mode")),
        )
    except ValueError as e:
        code = str(e)
        if code == "no_tokens":
            return {"error": "no_tokens"}, 400
        if code == "case_not_found":
            return {"error": "case_not_found"}, 404
        if code == "no_items":
            return {"error": "no_items"}, 400
        return {"error": "invalid_items_config"}, 400

    result["ok"] = True
    result["tokens_after"] = get_guest_tokens(guest_id, club_id)
    return result


@guest_bp.route("/api/cm-bonuses")
@guest_required
def api_cm_bonuses():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    return {
        "balance": get_cm_bonus_balance(guest["guest_id"], guest["club_id"]),
        "history": get_cm_bonus_history(guest["guest_id"], guest["club_id"], limit=10),
        "redeem_history": get_cm_bonus_redeem_history(guest["guest_id"], guest["club_id"], limit=30),
    }


@guest_bp.route("/api/cm-bonuses/redeem", methods=["POST"])
@guest_required
def api_cm_bonuses_redeem():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    try:
        result = redeem_cm_bonuses(guest)
    except ValueError as e:
        return {"error": "invalid_request", "message": str(e)}, 400
    except Exception as e:
        return {"error": "redeem_failed", "message": str(e)}, 500

    return result


@guest_bp.route("/logout")
@guest_required
def logout():
    _clear_guest_session()
    flash("Вы вышли из гостевого кабинета", "success")
    return redirect(url_for("guest.login"))


@guest_bp.route("/test-mode/stop", methods=["POST"])
@guest_required
def stop_test_mode():
    if not session.get("guest_test_mode"):
        _clear_guest_session()
        return redirect(url_for("guest.login"))

    source = session.get("guest_test_source")
    guest_id = session.get("guest_id")
    club_id = session.get("guest_club_id")

    if guest_id and club_id:
        record_audit_event(
            action="guest.test.stop",
            club_id=int(club_id),
            entity_type="guest",
            entity_id=guest_id,
            details={"source": source},
        )

    _clear_guest_session()

    if source == "admin_clubs" and session.get("role") == "admin":
        return redirect(url_for("admin.clubs_list"))
    if source == "owner_settings":
        return redirect(url_for("owner.settings", tab="club") + "#guest-login")
    if session.get("role") == "admin":
        return redirect(url_for("admin.clubs_list"))
    if session.get("role") in {"owner", "co-owner"} or session.get("impersonating_owner"):
        return redirect(url_for("owner.dashboard"))
    return redirect(url_for("guest.login"))


@guest_bp.route("/api/missions")
@guest_required
def api_guest_missions():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    return {"data": get_guest_missions_with_progress(guest_id, guest["club_id"])}
