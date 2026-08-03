from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.core import get_db_connection


def login():
    if request.method == "POST":
        login_value = request.form.get("login", "").strip()
        password = request.form.get("password", "").strip()

        if not login_value or not password:
            flash("Введи логин и пароль", "error")
            return redirect(url_for("login"))

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
                return redirect(url_for("login"))
            if not check_password_hash(user["pass_hash"], password):
                flash("Неверный пароль", "error")
                return redirect(url_for("login"))

            session["user_id"] = user["user_id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            session["login"] = user["login"]
            session["club_id"] = user["club_id"]
            session["club_name"] = user.get("club_name")

            if user["club_id"] is None:
                return redirect(url_for("club_create"))
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash(f"Ошибка авторизации: {e}", "error")
            return redirect(url_for("login"))
        finally:
            if conn:
                conn.close()

    return render_template("login.html")


def logout():
    session.clear()
    flash("Вы вышли из системы", "success")
    return redirect(url_for("login"))


def register_auth_routes(app):
    app.add_url_rule("/login", view_func=login, methods=["GET", "POST"])
    app.add_url_rule("/logout", view_func=logout)
