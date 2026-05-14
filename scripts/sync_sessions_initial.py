import logging
from datetime import datetime

import httpx
import pymysql
from pymysql.cursors import DictCursor

from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


logging.basicConfig(level=logging.INFO)

PAGE_LIMIT = 500


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
        connect_timeout=15,
        read_timeout=60,
        write_timeout=60,
        autocommit=False
    )


def get_club_data(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT club_id, lg_api_key, secret
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
            """, (club_id,))
            return cursor.fetchone()
    finally:
        conn.close()


# 🔥 получаем ВСЕ guest_id один раз
def get_existing_guest_ids(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT guest_id
                FROM guests
                WHERE club_id = %s
            """, (club_id,))
            return {row["guest_id"] for row in cursor.fetchall()}
    finally:
        conn.close()


def fetch_sessions_page(secret: str, api_key: str, page: int):
    url = f"https://{secret}.langame.ru/public_api/guests/sessions"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    params = {
        "page_limit": PAGE_LIMIT,
        "page": page
    }

    response = httpx.get(url, headers=headers, params=params, timeout=120)

    if response.status_code != 200:
        raise Exception(f"Ошибка API: {response.status_code} {response.text}")

    json_data = response.json()

    if not json_data.get("status"):
        raise Exception("API вернул status = false")

    return json_data


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except:
        return None


def filter_sessions(sessions: list, existing_guest_ids: set):
    filtered = []
    skipped = 0

    for s in sessions:
        if s.get("guest_id") in existing_guest_ids:
            filtered.append(s)
        else:
            skipped += 1

    return filtered, skipped


def prepare_sessions_rows(club_id: int, sessions: list):
    rows = []

    for s in sessions:
        rows.append((
            s.get("id"),
            club_id,
            s.get("UUID"),
            s.get("guest_id"),
            parse_datetime(s.get("date_start")),
            parse_datetime(s.get("date_stop"))
        ))

    return rows


def save_sessions(club_id: int, sessions: list):
    if not sessions:
        return

    rows = prepare_sessions_rows(club_id, sessions)

    sql = """
        INSERT INTO guest_sessions (
            id,
            club_id,
            uuid,
            guest_id,
            date_start,
            date_stop
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            uuid = VALUES(uuid),
            guest_id = VALUES(guest_id),
            date_start = VALUES(date_start),
            date_stop = VALUES(date_stop)
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
        conn.commit()
        logging.info(f"Сохранено: {len(rows)}")
    finally:
        conn.close()


def sync_sessions_initial(club_id: int):
    logging.info(f"Старт initial sync сессий для клуба {club_id}")

    club = get_club_data(club_id)
    if not club:
        raise Exception("Клуб не найден")

    api_key = club["lg_api_key"]
    secret = club["secret"]

    # 🔥 загружаем всех гостей ОДИН РАЗ
    existing_guest_ids = get_existing_guest_ids(club_id)
    logging.info(f"Загружено гостей: {len(existing_guest_ids)}")

    first_page = fetch_sessions_page(secret, api_key, page=1)

    total_pages = first_page.get("total_pages", 0)
    sessions = first_page.get("data", [])

    logging.info(f"Всего страниц: {total_pages}")

    filtered, skipped = filter_sessions(sessions, existing_guest_ids)

    logging.info(f"Страница 1: {len(filtered)} сохранено, {skipped} пропущено")

    save_sessions(club_id, filtered)

    for page in range(2, total_pages + 1):
        data = fetch_sessions_page(secret, api_key, page=page)
        sessions = data.get("data", [])

        filtered, skipped = filter_sessions(sessions, existing_guest_ids)

        logging.info(
            f"Страница {page}/{total_pages}: {len(filtered)} сохранено, {skipped} пропущено"
        )

        save_sessions(club_id, filtered)

    logging.info("Initial sync завершен")


if __name__ == "__main__":
    sync_sessions_initial(1)