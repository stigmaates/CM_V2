from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from app.services.guest_auth import create_guest_login_token, get_guest_by_id, get_guest_login_token
from app.services.missions import get_guest_missions_with_progress
from app.services.wheel import get_guest_profile_stats, get_guest_tokens, get_wheel_prizes, get_wheel_settings, save_guest_wheel_spin, serialize_wheel_prize, choose_wheel_prize


def guest_dashboard():
    if not session.get("guest_logged_in"):
        return redirect(url_for("guest_login"))

    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        flash("Гость не найден", "error")
        return redirect(url_for("guest_login"))

    missions = get_guest_missions_with_progress(
        guest_id=guest["guest_id"],
        club_id=guest["club_id"]
    )

    profile_stats = get_guest_profile_stats(
        guest_id=guest["guest_id"],
        club_id=guest["club_id"]
    )

    return render_template(
        "guest_dashboard.html",
        guest_name=session.get("guest_name"),
        guest_id=session.get("guest_id"),
        missions=missions,
        profile_stats=profile_stats,
    )


def guest_check_login():
    token = request.args.get("token", "").strip()
    if not token:
        return {"ok": False, "error": "token_required"}, 400

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

    return {"ok": True, "status": "confirmed", "redirect_url": url_for("guest_dashboard")}


def guest_login():
    bot_username = "club_module_bot"
    token = create_guest_login_token()
    bot_link = f"https://t.me/{bot_username}?start=login_{token}"
    return render_template("guest_login.html", bot_link=bot_link, token=token)


def api_guest_tokens():
    if not session.get("guest_logged_in"):
        return {"error": "unauthorized"}, 401

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
            "spin_cost": 1,
            "message": "Колесо фортуны пока не настроено для этого клуба",
        }

    tokens = get_guest_tokens(guest_id, club_id)

    return {
        "tokens": tokens,
        "is_enabled": bool(settings.get("is_enabled")),
        "spin_cost": settings.get("spin_cost", 1),
        "tokens_start_date": settings.get("tokens_start_date").isoformat() if settings.get("tokens_start_date") else None,
    }


def api_wheel_spin():
    if not session.get("guest_logged_in"):
        return {"error": "unauthorized"}, 401

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

    spin_cost = int(settings.get("spin_cost") or 1)
    if spin_cost <= 0:
        spin_cost = 1

    tokens = get_guest_tokens(guest_id, club_id)
    if tokens < spin_cost:
        return {"error": "no_tokens"}, 400

    prizes = get_wheel_prizes(club_id)
    if not prizes:
        return {"error": "no_prizes"}, 400

    prize = choose_wheel_prize(prizes)
    if not prize:
        return {"error": "invalid_prizes_config"}, 400

    spin_id = save_guest_wheel_spin(
        guest_id=guest_id,
        club_id=club_id,
        prize_id=prize["id"],
        spent_tokens=spin_cost,
    )

    tokens_after = get_guest_tokens(guest_id, club_id)

    return {
        "ok": True,
        "spin_id": spin_id,
        "tokens_after": tokens_after,
        "prize": serialize_wheel_prize(prize),
    }


def guest_logout():
    session.pop("guest_id", None)
    session.pop("guest_club_id", None)
    session.pop("guest_name", None)
    session.pop("guest_telegram_id", None)
    session.pop("guest_logged_in", None)
    flash("Вы вышли из гостевого кабинета", "success")
    return redirect(url_for("guest_login"))


def api_guest_missions():
    if not session.get("guest_logged_in"):
        return {"error": "unauthorized"}, 401

    guest_id = session.get("guest_id")
    guest = get_guest_by_id(guest_id, session.get("guest_club_id"))
    if not guest:
        return {"error": "guest_not_found"}, 404
    
    return {"data": get_guest_missions_with_progress(guest_id, guest["club_id"])}


def register_guest_routes(app):
    app.add_url_rule('/guest/dashboard', view_func=guest_dashboard)
    app.add_url_rule('/guest/check-login', view_func=guest_check_login)
    app.add_url_rule('/guest/login', view_func=guest_login)
    app.add_url_rule('/api/guest/tokens', view_func=api_guest_tokens)
    app.add_url_rule('/api/wheel/spin', view_func=api_wheel_spin, methods=['POST'])
    app.add_url_rule('/guest/logout', view_func=guest_logout)
    app.add_url_rule('/api/guest/missions', view_func=api_guest_missions)
