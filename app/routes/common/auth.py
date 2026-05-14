from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.core import get_db_connection

from . import auth_bp


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
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
                    SELECT user_id, role, name, login, club_id, pass_hash
                    FROM users
                    WHERE login = %s
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

            session["user_id"] = user["user_id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            session["login"] = user["login"]
            session["club_id"] = user["club_id"]

            if user["role"] == "admin":
                return redirect(url_for("admin.dashboard"))
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

from functools import wraps
from flask import session, redirect


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
        if session.get("role") != "owner":
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
