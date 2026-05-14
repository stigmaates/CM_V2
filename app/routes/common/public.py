from flask import redirect, session, url_for

from . import public_bp


@public_bp.route("/")
def index():
    if session.get("guest_logged_in"):
        return redirect(url_for("guest.dashboard"))
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin.users_create"))
        return redirect(url_for("owner.dashboard"))
    return redirect(url_for("auth.login"))
