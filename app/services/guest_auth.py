import secrets
from datetime import datetime, timedelta

from app.core import get_db_connection


def create_guest_login_token():
    token = secrets.token_urlsafe(32)
    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(minutes=10)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO guest_login_tokens (
                    token,
                    guest_id,
                    telegram_id,
                    is_confirmed,
                    created_at,
                    expires_at
                )
                VALUES (%s, NULL, NULL, 0, %s, %s)
                """,
                (token, created_at, expires_at),
            )
        conn.commit()
        return token
    finally:
        conn.close()


def get_guest_login_token(token: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token, guest_id, telegram_id, is_confirmed, created_at, expires_at
                FROM guest_login_tokens
                WHERE token = %s
                LIMIT 1
                """,
                (token,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_guest_by_id(guest_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT guest_id, club_id, phone, fio, telegram_id
                FROM guests
                WHERE guest_id = %s
                LIMIT 1
                """,
                (guest_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()
