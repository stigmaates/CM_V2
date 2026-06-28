from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote_plus

import pymysql
from flask import Flask, redirect, session, url_for
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


def create_flask_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
    # Limit image upload requests at Flask level. Per-club quota is checked separately.
    app.config["MAX_CONTENT_LENGTH"] = int(CLUBMODULE_IMAGE_MAX_MB or 5) * 1024 * 1024 + 1024 * 1024
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
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth.login"))
            if session.get("role") not in allowed_roles:
                target = "admin.users_create" if session.get("role") == "admin" else "owner.dashboard"
                return redirect(url_for(target))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(func):
    return role_required("admin")(func)


def is_owner_access_session():
    """Allow real owners and admins who opened a club in owner-impersonation mode."""
    if session.get("role") == "owner":
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
            target = "admin.clubs_list" if session.get("role") == "admin" else "auth.login"
            return redirect(url_for(target))
        return func(*args, **kwargs)

    return wrapper


def guest_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("guest_logged_in"):
            return redirect(url_for("guest.login"))
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
