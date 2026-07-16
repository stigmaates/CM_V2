from datetime import datetime
from urllib.parse import quote_plus

from flask import flash, redirect, render_template, request, session, url_for

from app.core import guest_required
from app.config import BOT_USERNAME
from app.services.rate_limit import client_ip, is_rate_limited
from app.services.guest_auth import create_guest_login_token, get_guest_by_id, get_guest_login_token
from app.services.missions import get_guest_missions_with_progress
from app.services.cm_bonuses import get_cm_bonus_balance, get_cm_bonus_history, get_cm_bonus_redeem_history, redeem_cm_bonuses
from app.services.prize_claims import get_prize_claim_by_spin_id, serialize_prize_claim
from app.services.cases import (
    get_cases,
    get_game_mode,
    get_guest_case_history,
    open_case,
    serialize_case,
)
from app.services.wheel import (
    choose_wheel_prize,
    get_guest_profile_stats,
    get_guest_streak_info,
    get_guest_tokens,
    get_guest_token_history,
    get_guest_wheel_history,
    get_wheel_prizes,
    get_wheel_settings,
    save_guest_wheel_spin,
    serialize_wheel_prize,
    sync_guest_wheel_tokens,
)

from . import guest_bp


@guest_bp.route('/dashboard')
@guest_required
def dashboard():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        flash("Гость не найден", "error")
        return redirect(url_for("guest.login"))

    sync_guest_wheel_tokens(guest_id=guest["guest_id"], club_id=guest["club_id"])

    missions = get_guest_missions_with_progress(guest_id=guest["guest_id"], club_id=guest["club_id"])
    profile_stats = get_guest_profile_stats(guest_id=guest["guest_id"], club_id=guest["club_id"])
    wheel_settings = get_wheel_settings(guest["club_id"])
    wheel_prizes = [serialize_wheel_prize(p) for p in get_wheel_prizes(guest["club_id"])]
    wheel_history = get_guest_wheel_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=8)
    game_mode = get_game_mode(guest["club_id"])
    cases = [serialize_case(c) for c in get_cases(guest["club_id"])]
    case_history = get_guest_case_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=8)
    token_balance = get_guest_tokens(guest_id=guest["guest_id"], club_id=guest["club_id"])
    token_history = get_guest_token_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=20)
    streak_info = get_guest_streak_info(guest_id=guest["guest_id"], club_id=guest["club_id"])
    cm_bonus_balance = get_cm_bonus_balance(guest_id=guest["guest_id"], club_id=guest["club_id"])
    cm_bonus_history = get_cm_bonus_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=10)
    cm_bonus_redeem_history = get_cm_bonus_redeem_history(guest_id=guest["guest_id"], club_id=guest["club_id"], limit=30)

    return render_template(
        "guest/guest_dashboard.html",
        guest_name=session.get("guest_name"),
        guest_id=session.get("guest_id"),
        missions=missions,
        guest_missions=missions,
        profile_stats=profile_stats,
        wheel_settings=wheel_settings,
        wheel_prizes=wheel_prizes,
        wheel_history=wheel_history,
        game_mode=game_mode,
        cases=cases,
        case_history=case_history,
        token_balance=token_balance,
        token_history=token_history,
        streak_info=streak_info,
        cm_bonus_balance=cm_bonus_balance,
        cm_bonus_history=cm_bonus_history,
        cm_bonus_redeem_history=cm_bonus_redeem_history,
    )


@guest_bp.route('/check-login')
def check_login():
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


@guest_bp.route('/login')
def login():
    bot_username = BOT_USERNAME.lstrip("@")
    token = create_guest_login_token()
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
    )


@guest_bp.route('/api/tokens')
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
        "tokens_start_date": settings.get("tokens_start_date").isoformat() if settings.get("tokens_start_date") else None,
    }


@guest_bp.route('/api/wheel/spin', methods=['POST'])
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

    prize = choose_wheel_prize(prizes)
    if not prize:
        return {"error": "invalid_prizes_config"}, 400

    try:
        spin_id = save_guest_wheel_spin(
            guest_id=guest_id,
            club_id=club_id,
            prize_id=prize["id"],
            spent_tokens=spin_cost,
        )
    except ValueError:
        return {"error": "no_tokens"}, 400

    tokens_after = get_guest_tokens(guest_id, club_id)

    claim = get_prize_claim_by_spin_id(spin_id)

    return {
        "ok": True,
        "spin_id": spin_id,
        "tokens_after": tokens_after,
        "prize": serialize_wheel_prize(prize),
        "claim": serialize_prize_claim(claim),
    }


@guest_bp.route('/api/cases')
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


@guest_bp.route('/api/cases/<int:case_id>/open', methods=['POST'])
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
        result = open_case(guest_id=guest_id, club_id=club_id, case_id=case_id)
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


@guest_bp.route('/api/cm-bonuses')
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


@guest_bp.route('/api/cm-bonuses/redeem', methods=['POST'])
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



@guest_bp.route('/logout')
@guest_required
def logout():
    session.pop("guest_id", None)
    session.pop("guest_club_id", None)
    session.pop("guest_name", None)
    session.pop("guest_telegram_id", None)
    session.pop("guest_logged_in", None)
    flash("Вы вышли из гостевого кабинета", "success")
    return redirect(url_for("guest.login"))


@guest_bp.route('/api/missions')
@guest_required
def api_guest_missions():
    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404

    return {"data": get_guest_missions_with_progress(guest_id, guest["club_id"])}
