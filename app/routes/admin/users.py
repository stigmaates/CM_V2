from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.core import admin_required, get_db_connection

from . import admin_bp


@admin_bp.route("/users/create", methods=["GET", "POST"])
@admin_required
def users_create():
    if request.method == "POST":
        role = request.form.get("role", "").strip()
        name = request.form.get("name", "").strip()
        login_value = request.form.get("login", "").strip()
        club_id = request.form.get("club_id", "").strip()
        password = request.form.get("password", "").strip()

        if not role or not name or not login_value or not password:
            flash("Заполни обязательные поля", "error")
            return redirect(url_for("admin.users_create"))

        if club_id == "":
            club_id = None
        else:
            try:
                club_id = int(club_id)
            except ValueError:
                flash("club_id должен быть числом", "error")
                return redirect(url_for("admin.users_create"))

        pass_hash = generate_password_hash(password)
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT user_id FROM users WHERE login = %s LIMIT 1", (login_value,))
                if cursor.fetchone():
                    flash("Пользователь с таким логином уже существует", "error")
                    return redirect(url_for("admin.users_create"))

                cursor.execute(
                    """
                    INSERT INTO users (role, name, login, club_id, created_at, pass_hash)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (role, name, login_value, club_id, datetime.utcnow(), pass_hash),
                )

            conn.commit()
            flash("Пользователь успешно создан", "success")
            return redirect(url_for("admin.users_create"))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f"Ошибка при создании пользователя: {e}", "error")
            return redirect(url_for("admin.users_create"))
        finally:
            if conn:
                conn.close()

    return render_template("admin/create_user.html")
