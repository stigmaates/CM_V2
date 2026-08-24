from werkzeug.security import check_password_hash, generate_password_hash

from app.core import get_db_connection


def get_owner_profile(user_id: int, club_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.user_id,
                    u.name,
                    u.login,
                    u.role,
                    u.club_id,
                    c.name AS club_name
                FROM users u
                JOIN clubs c ON c.club_id = u.club_id
                WHERE u.user_id = %s
                  AND u.club_id = %s
                  AND u.role IN ('owner', 'co-owner')
                LIMIT 1
                """,
                (user_id, club_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def update_owner_profile(
    *,
    user_id: int,
    club_id: int,
    name: str,
    current_password: str = "",
    new_password: str = "",
) -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Укажи имя")
    if len(clean_name) > 255:
        raise ValueError("Имя не должно быть длиннее 255 символов")
    if new_password and len(new_password) < 8:
        raise ValueError("Новый пароль должен содержать не менее 8 символов")
    if new_password and not current_password:
        raise ValueError("Введи текущий пароль")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, pass_hash
                FROM users
                WHERE user_id = %s
                  AND club_id = %s
                  AND role IN ('owner', 'co-owner')
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, club_id),
            )
            user = cursor.fetchone()
            if not user:
                raise ValueError("Профиль владельца не найден")

            password_changed = bool(new_password)
            if password_changed and not check_password_hash(user["pass_hash"], current_password):
                raise ValueError("Текущий пароль указан неверно")

            if password_changed:
                cursor.execute(
                    "UPDATE users SET name = %s, pass_hash = %s WHERE user_id = %s AND club_id = %s",
                    (clean_name, generate_password_hash(new_password), user_id, club_id),
                )
            else:
                cursor.execute(
                    "UPDATE users SET name = %s WHERE user_id = %s AND club_id = %s",
                    (clean_name, user_id, club_id),
                )
        conn.commit()
        return {"name": clean_name, "password_changed": password_changed}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
