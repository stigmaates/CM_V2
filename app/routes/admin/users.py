from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.core import admin_required, get_db_connection

from . import admin_bp


def _fetch_admin_users(cursor) -> list[dict]:
    last_login_expr = "u.last_login_at" if _users_column_exists(cursor, "last_login_at") else "NULL"
    cursor.execute(f"""
        SELECT
            u.user_id,
            u.role,
            u.name,
            u.login,
            u.club_id,
            u.created_at,
            {last_login_expr} AS last_login_at,
            c.name AS club_name
        FROM users u
        LEFT JOIN clubs c ON c.club_id = u.club_id
        ORDER BY u.created_at DESC, u.user_id DESC
        """)
    return cursor.fetchall() or []


def _fetch_admin_user(cursor, user_id: int) -> dict | None:
    last_login_expr = "u.last_login_at" if _users_column_exists(cursor, "last_login_at") else "NULL"
    cursor.execute(
        f"""
        SELECT
            u.user_id,
            u.role,
            u.name,
            u.login,
            u.club_id,
            u.created_at,
            {last_login_expr} AS last_login_at,
            c.name AS club_name
        FROM users u
        LEFT JOIN clubs c ON c.club_id = u.club_id
        WHERE u.user_id = %s
        LIMIT 1
        """,
        (user_id,),
    )
    return cursor.fetchone()


def _users_column_exists(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = %s
        """,
        (column_name,),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


@admin_bp.route("/users")
@admin_required
def users_list():
    selected_user_id = request.args.get("user_id", "").strip()
    selected_user = None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            users = _fetch_admin_users(cursor)
            if selected_user_id:
                try:
                    selected_user = _fetch_admin_user(cursor, int(selected_user_id))
                except ValueError:
                    selected_user = None
            if not selected_user and users:
                selected_user = users[0]
    finally:
        conn.close()

    return render_template(
        "admin/users.html",
        users=users,
        selected_user=selected_user,
        active_page="users",
    )


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def user_reset_password(user_id: int):
    password = request.form.get("password", "").strip()
    password_confirm = request.form.get("password_confirm", "").strip()

    if not password:
        flash("Новый пароль не может быть пустым", "error")
        return redirect(url_for("admin.users_list", user_id=user_id))
    if password != password_confirm:
        flash("Пароли не совпадают", "error")
        return redirect(url_for("admin.users_list", user_id=user_id))
    if len(password) < 6:
        flash("Пароль должен быть не короче 6 символов", "error")
        return redirect(url_for("admin.users_list", user_id=user_id))

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            user = _fetch_admin_user(cursor, user_id)
            if not user:
                flash("Пользователь не найден", "error")
                return redirect(url_for("admin.users_list"))
            cursor.execute(
                "UPDATE users SET pass_hash = %s WHERE user_id = %s",
                (generate_password_hash(password), user_id),
            )
        conn.commit()
        flash(f"Пароль пользователя {user['login']} обновлён", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ошибка при сбросе пароля: {e}", "error")
    finally:
        if conn:
            conn.close()

    return redirect(url_for("admin.users_list", user_id=user_id))


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

        if role not in {"admin", "owner", "reception"}:
            flash("Недопустимая роль пользователя", "error")
            return redirect(url_for("admin.users_create"))

        if club_id == "":
            club_id = None
        else:
            try:
                club_id = int(club_id)
            except ValueError:
                flash("club_id должен быть числом", "error")
                return redirect(url_for("admin.users_create"))

        if role in {"owner", "reception"} and club_id is None:
            flash("Для owner и reception нужно указать club_id", "error")
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

    return render_template("admin/create_user.html", active_page="users_create")
