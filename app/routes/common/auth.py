from datetime import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.core import OWNER_ACCESS_ROLES, get_db_connection
from app.services.rate_limit import client_ip, is_rate_limited

from . import auth_bp


def _mark_user_last_login(cursor, user_id: int) -> None:
    try:
        cursor.execute(
            "UPDATE users SET last_login_at = %s WHERE user_id = %s",
            (datetime.utcnow(), user_id),
        )
    except Exception:
        # Compatibility for deployments where code is pulled before migrations run.
        return


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = client_ip()
        if is_rate_limited(f"auth.login:{ip}", limit=10, window_seconds=300):
            flash("Слишком много попыток входа. Попробуйте позже.", "error")
            return redirect(url_for("auth.login"))

        login_value = request.form.get("login", "").strip()
        password = request.form.get("password", "").strip()

        if not login_value or not password:
            flash("Введи логин и пароль", "error")
            return redirect(url_for("auth.login"))

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        u.user_id,
                        u.role,
                        u.name,
                        u.login,
                        u.club_id,
                        u.pass_hash,
                        c.name AS club_name
                    FROM users u
                    LEFT JOIN clubs c ON c.club_id = u.club_id
                    WHERE u.login = %s
                    LIMIT 1
                    """,
                    (login_value,),
                )
                user = cursor.fetchone()

            if not user:
                flash("Пользователь не найден", "error")
                return redirect(url_for("auth.login"))
            if not check_password_hash(user["pass_hash"], password):
                flash("Неверный пароль", "error")
                return redirect(url_for("auth.login"))

            with conn.cursor() as cursor:
                _mark_user_last_login(cursor, user["user_id"])
            conn.commit()

            session["user_id"] = user["user_id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            session["login"] = user["login"]
            session["club_id"] = user["club_id"]
            session["club_name"] = user.get("club_name")

            if user["role"] == "admin":
                return redirect(url_for("admin.dashboard"))
            if user["role"] == "reception":
                return redirect(url_for("reception.dashboard"))
            if user["club_id"] is None:
                return redirect(url_for("owner.club_create"))
            return redirect(url_for("owner.dashboard"))
        except Exception as e:
            flash(f"Ошибка авторизации: {e}", "error")
            return redirect(url_for("auth.login"))
        finally:
            if conn:
                conn.close()

    return render_template("login.html")


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return view_func(*args, **kwargs)

    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        if session.get("role") != "admin":
            return "Доступ запрещён", 403
        return view_func(*args, **kwargs)

    return wrapper


def owner_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        is_owner = session.get("role") in OWNER_ACCESS_ROLES
        is_admin_impersonation = (
            session.get("role") == "admin"
            and bool(session.get("impersonating_owner"))
            and session.get("impersonated_club_id") is not None
            and session.get("club_id") is not None
        )
        if not (is_owner or is_admin_impersonation):
            return "Доступ запрещён", 403
        return view_func(*args, **kwargs)

    return wrapper


def guest_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "guest_id" not in session:
            return redirect("/guest/login")
        return view_func(*args, **kwargs)

    return wrapper


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы", "success")
    return redirect(url_for("auth.login"))
