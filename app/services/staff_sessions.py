"""Revalidate staff authority on every request; password/role changes revoke sessions."""

import hashlib
import hmac
import json
import time

from flask import current_app, jsonify, redirect, request, session

STAFF_SESSION_SECONDS = 12 * 60 * 60


def authority_stamp(user):
    fields = [user.get(key) for key in ("user_id", "role", "club_id", "pass_hash")]
    payload = json.dumps(fields, separators=(",", ":"), default=str).encode()
    return hmac.new(current_app.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def establish_staff_session(user):
    # Do not carry impersonation, guest identity or CSRF state across a fresh login.
    session.clear()
    for key in ("user_id", "role", "name", "login", "club_id", "club_name"):
        session[key] = user.get(key)
    session["_staff_authority"] = authority_stamp(user)
    session["_staff_login_at"] = time.time()


def load_staff_user(user_id):
    from app.core import get_db_connection

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, role, club_id, pass_hash FROM users WHERE user_id=%s LIMIT 1", (user_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def register_staff_session_guard(app):
    @app.before_request
    def validate_staff_session():
        if "user_id" not in session:
            return None
        endpoint = request.endpoint or ""
        if endpoint.startswith(("static", "demo.")) or endpoint in ("auth.login", "auth.logout"):
            return None
        if request.path in ("/healthz", "/readyz"):
            return None
        try:
            age = time.time() - float(session.get("_staff_login_at", 0))
        except (ValueError, TypeError):
            age = -1
        stamp = session.get("_staff_authority")
        valid = isinstance(stamp, str) and 0 <= age < STAFF_SESSION_SECONDS
        if valid:
            try:
                user = load_staff_user(session["user_id"])
            except Exception:
                # Fail closed without exposing a database exception or logging credentials.
                return jsonify(ok=False, error="authentication_unavailable"), 503
            valid = bool(user and hmac.compare_digest(stamp, authority_stamp(user)))
            if valid:
                valid = session.get("role") == user["role"]
                # Admin impersonation deliberately changes the effective club, not the actor.
                if user["role"] != "admin":
                    valid = valid and session.get("club_id") == user.get("club_id")
        if valid:
            return None
        session.clear()
        if (
            request.path.startswith("/api/")
            or request.is_json
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        ):
            return jsonify(ok=False, error="login_required"), 401
        return redirect("/login")
