import secrets
from datetime import datetime, timedelta

from app.core import get_db_connection

_guest_login_tokens_club_column_ready = False


def ensure_guest_login_tokens_club_column(cursor):
    """Add club_id to guest_login_tokens for multi-club guest identity."""
    global _guest_login_tokens_club_column_ready
    if _guest_login_tokens_club_column_ready:
        return

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'guest_login_tokens'
          AND COLUMN_NAME = 'club_id'
        """)
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE guest_login_tokens
            ADD COLUMN club_id INT NULL AFTER guest_id
            """)
    _guest_login_tokens_club_column_ready = True


def create_guest_login_token(club_id: int | None = None):
    token = secrets.token_urlsafe(32)
    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(minutes=10)
    club_id_value = int(club_id) if club_id is not None else None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_guest_login_tokens_club_column(cursor)
            cursor.execute(
                """
                INSERT INTO guest_login_tokens (
                    token,
                    guest_id,
                    club_id,
                    telegram_id,
                    is_confirmed,
                    created_at,
                    expires_at
                )
                VALUES (%s, NULL, %s, NULL, 0, %s, %s)
                """,
                (token, club_id_value, created_at, expires_at),
            )
        conn.commit()
        return token
    finally:
        conn.close()


def get_guest_login_club(club_id: int | None = None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if club_id is not None:
                cursor.execute(
                    """
                    SELECT club_id, name
                    FROM clubs
                    WHERE club_id = %s
                    LIMIT 1
                    """,
                    (int(club_id),),
                )
                return cursor.fetchone()

            cursor.execute("""
                SELECT club_id, name
                FROM clubs
                ORDER BY club_id
                LIMIT 2
                """)
            rows = cursor.fetchall() or []
            if len(rows) == 1:
                return rows[0]
            return None
    finally:
        conn.close()


def get_guest_login_token(token: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_guest_login_tokens_club_column(cursor)
            cursor.execute(
                """
                SELECT token, guest_id, club_id, telegram_id, is_confirmed, created_at, expires_at
                FROM guest_login_tokens
                WHERE token = %s
                LIMIT 1
                """,
                (token,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_guest_by_id(guest_id: int, club_id: int | None = None):
    """Return a guest by the composite identity (club_id, guest_id).

    guest_id is not globally unique across Langame clubs. When club_id is known,
    always use it. The club_id=None fallback is kept only for old sessions; it
    returns a guest only when guest_id exists exactly once, otherwise None.
    """
    if not guest_id:
        return None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if club_id is not None:
                cursor.execute(
                    """
                    SELECT guest_id, club_id, phone, fio, telegram_id
                    FROM guests
                    WHERE club_id = %s
                      AND guest_id = %s
                    LIMIT 1
                    """,
                    (club_id, guest_id),
                )
                return cursor.fetchone()

            cursor.execute(
                """
                SELECT guest_id, club_id, phone, fio, telegram_id
                FROM guests
                WHERE guest_id = %s
                LIMIT 2
                """,
                (guest_id,),
            )
            rows = cursor.fetchall() or []
            if len(rows) == 1:
                return rows[0]
            return None
    finally:
        conn.close()
