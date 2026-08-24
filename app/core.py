import hmac
import secrets
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote_plus

import pymysql
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from pymysql.cursors import DictCursor
from sqlalchemy import create_engine

from app.config import (
    CLUBMODULE_IMAGE_MAX_MB,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    IS_PRODUCTION,
    SECRET_KEY,
)

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER_NAMES = ("X-CSRFToken", "X-CSRF-Token")
CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
OWNER_ACCESS_ROLES = {"owner", "co-owner"}


def generate_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _get_request_csrf_token() -> str:
    for header_name in CSRF_HEADER_NAMES:
        token = request.headers.get(header_name)
        if token:
            return token
    return request.form.get(CSRF_FORM_FIELD, "")


def validate_csrf_token() -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    supplied = _get_request_csrf_token()
    return bool(expected and supplied and hmac.compare_digest(str(expected), str(supplied)))


def _csrf_error_response():
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"ok": False, "error": "csrf_failed"}), 400
    abort(400, description="CSRF token is missing or invalid")


def _wants_json_response() -> bool:
    return request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html


def _auth_error_response(error: str, status_code: int):
    if _wants_json_response():
        return jsonify({"ok": False, "status": False, "error": error}), status_code
    return None


def register_csrf_protection(flask_app: Flask) -> None:
    @flask_app.before_request
    def csrf_protect():
        if request.method not in CSRF_UNSAFE_METHODS:
            return None
        if validate_csrf_token():
            return None
        return _csrf_error_response()

    @flask_app.context_processor
    def inject_csrf_token():
        return {
            "csrf_token": generate_csrf_token,
            "csrf_field_name": CSRF_FORM_FIELD,
        }


def is_club_service_enabled(club_id) -> bool:
    if club_id is None:
        return True

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT service_enabled
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            row = cursor.fetchone()
        if not row:
            return True
        return bool(int(row.get("service_enabled") if row.get("service_enabled") is not None else 1))
    except Exception:
        # Keep the app available if code is deployed before migrations are applied.
        return True
    finally:
        if conn:
            conn.close()


def _service_gate_club_id():
    if session.get("role") == "admin":
        return None
    if session.get("guest_logged_in"):
        return session.get("guest_club_id")
    if session.get("role") in {*OWNER_ACCESS_ROLES, "reception"}:
        return session.get("club_id")
    return None


def register_club_service_gate(flask_app: Flask) -> None:
    @flask_app.before_request
    def club_service_gate():
        endpoint = request.endpoint or ""
        if endpoint.startswith("static") or endpoint.startswith("admin."):
            return None
        if endpoint in {"auth.logout", "auth.login"}:
            return None

        club_id = _service_gate_club_id()
        if club_id is None or is_club_service_enabled(club_id):
            return None

        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"ok": False, "error": "club_service_disabled"}), 403
        return render_template("service_unavailable.html", club_name=session.get("club_name")), 403


def create_flask_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
    # Limit image upload requests at Flask level. Per-club quota is checked separately.
    app.config["MAX_CONTENT_LENGTH"] = int(CLUBMODULE_IMAGE_MAX_MB or 5) * 1024 * 1024 + 1024 * 1024
    register_csrf_protection(app)
    register_club_service_gate(app)
    return app


app = create_flask_app()

encoded_password = quote_plus(DB_PASSWORD)
engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4",
    connect_args={"ssl": {}},
    pool_pre_ping=True,
)


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        ssl={"check_hostname": False},
    )


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            json_response = _auth_error_response("login_required", 401)
            if json_response:
                return json_response
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                json_response = _auth_error_response("login_required", 401)
                if json_response:
                    return json_response
                return redirect(url_for("auth.login"))
            if session.get("role") not in allowed_roles:
                json_response = _auth_error_response("forbidden", 403)
                if json_response:
                    return json_response
                if session.get("role") == "admin":
                    target = "admin.users_create"
                elif session.get("role") == "reception":
                    target = "reception.dashboard"
                else:
                    target = "owner.dashboard"
                return redirect(url_for(target))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(func):
    return role_required("admin")(func)


def reception_required(func):
    return role_required("reception")(func)


def is_owner_access_session():
    """Allow real owners and admins who opened a club in owner-impersonation mode."""
    if session.get("role") in OWNER_ACCESS_ROLES:
        return True
    return (
        session.get("role") == "admin"
        and bool(session.get("impersonating_owner"))
        and session.get("impersonated_club_id") is not None
        and session.get("club_id") is not None
    )


def owner_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not is_owner_access_session():
            if session.get("role") == "admin":
                target = "admin.clubs_list"
            elif session.get("role") == "reception":
                target = "reception.dashboard"
            else:
                target = "auth.login"
            return redirect(url_for(target))
        return func(*args, **kwargs)

    return wrapper


def guest_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("guest_logged_in"):
            return redirect(url_for("guest.login"))
        if request.endpoint not in {"guest.logout", "guest.stop_test_mode"}:
            guest_id = session.get("guest_id")
            club_id = session.get("guest_club_id")
            if guest_id and club_id:
                from app.services.guest_management import is_guest_module_banned

                if is_guest_module_banned(club_id=int(club_id), guest_id=int(guest_id)):
                    if request.path.startswith("/guest/api/") or (
                        request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
                    ):
                        return (
                            jsonify(
                                {
                                    "error": "guest_banned",
                                    "message": "Пожалуйста, обратитесь к администрации клуба",
                                }
                            ),
                            403,
                        )
                    return render_template("guest/module_banned.html"), 403
        return func(*args, **kwargs)

    return wrapper


def parse_datetime_local(value: str):
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    raise ValueError("Неверный формат даты")


def calc_percent_change(current, previous):
    if previous is None or previous == 0:
        if current and current > 0:
            return 100.0
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


def get_period_range(days: int):
    now = datetime.now()
    current_end = now
    current_start = now - timedelta(days=days)

    previous_end = current_start
    previous_start = current_start - timedelta(days=days)

    return {
        "current_start": current_start,
        "current_end": current_end,
        "previous_start": previous_start,
        "previous_end": previous_end,
    }


def format_date(dt):
    return dt.strftime("%d.%m.%Y")
