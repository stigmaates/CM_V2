from app.core import get_db_connection
from app.services.timezones import DEFAULT_CLUB_TIMEZONE, validate_club_timezone

_club_bonus_chat_column_ready = False
_club_timezone_column_ready = False


def ensure_club_bonus_chat_column(cursor) -> None:
    """Add per-club Telegram chat id for КБ transfer notifications."""
    global _club_bonus_chat_column_ready
    if _club_bonus_chat_column_ready:
        return

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clubs'
          AND COLUMN_NAME = 'cm_bonus_admin_chat_id'
        """)
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute("""
            ALTER TABLE clubs
            ADD COLUMN cm_bonus_admin_chat_id VARCHAR(80) NULL AFTER secret
            """)
    _club_bonus_chat_column_ready = True


def ensure_club_timezone_column(cursor) -> None:
    """Add the IANA timezone used for club-local schedules."""
    global _club_timezone_column_ready
    if _club_timezone_column_ready:
        return

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clubs'
          AND COLUMN_NAME = 'timezone'
        """)
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute(f"""
            ALTER TABLE clubs
            ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_CLUB_TIMEZONE}' AFTER name
            """)
    _club_timezone_column_ready = True


def get_club_info(club_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_club_bonus_chat_column(cursor)
            ensure_club_timezone_column(cursor)
            from app.services.first_visit_survey import ensure_club_social_columns

            ensure_club_social_columns(cursor)
            cursor.execute(
                """
                SELECT
                    club_id,
                    owner_id,
                    name,
                    timezone,
                    lg_api_key,
                    secret,
                    cm_bonus_admin_chat_id,
                    instagram_url,
                    youtube_url,
                    vk_url,
                    telegram_channel_url,
                    yandex_maps_url,
                    two_gis_url
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            row = cursor.fetchone()
        conn.commit()
        return row
    finally:
        conn.close()


def update_club_info(
    club_id,
    name: str,
    lg_api_key: str,
    secret: str,
    cm_bonus_admin_chat_id: str | None = None,
    instagram_url: str | None = None,
    youtube_url: str | None = None,
    vk_url: str | None = None,
    telegram_channel_url: str | None = None,
    yandex_maps_url: str | None = None,
    two_gis_url: str | None = None,
    timezone_name: str | None = None,
):
    timezone_name = validate_club_timezone(timezone_name) if timezone_name is not None else None
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_club_bonus_chat_column(cursor)
            ensure_club_timezone_column(cursor)
            from app.services.first_visit_survey import ensure_club_social_columns

            ensure_club_social_columns(cursor)
            cursor.execute(
                """
                UPDATE clubs
                SET name = %s,
                    timezone = COALESCE(%s, timezone),
                    lg_api_key = %s,
                    secret = %s,
                    cm_bonus_admin_chat_id = %s,
                    instagram_url = %s,
                    youtube_url = %s,
                    vk_url = %s,
                    telegram_channel_url = %s,
                    yandex_maps_url = %s,
                    two_gis_url = %s
                WHERE club_id = %s
                """,
                (
                    name,
                    timezone_name,
                    lg_api_key,
                    secret,
                    (cm_bonus_admin_chat_id or "").strip() or None,
                    (instagram_url or "").strip() or None,
                    (youtube_url or "").strip() or None,
                    (vk_url or "").strip() or None,
                    (telegram_channel_url or "").strip() or None,
                    (yandex_maps_url or "").strip() or None,
                    (two_gis_url or "").strip() or None,
                    club_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()
