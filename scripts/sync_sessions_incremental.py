import logging
from datetime import datetime, timedelta

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


def get_clubs():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT club_id, lg_api_key, secret
                FROM clubs
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def fetch_sessions(secret, api_key, page, date_from, date_to):
    url = f"https://{secret}.langame.ru/public_api/guests/sessions"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    params = {
        "page_limit": PAGE_LIMIT,
        "page": page,
        "date_from": date_from,
        "date_to": date_to
    }

    response = httpx.get(url, headers=headers, params=params, timeout=60)

    if response.status_code != 200:
        raise Exception(f"Ошибка API: {response.status_code}")

    data = response.json()

    if not data.get("status"):
        raise Exception("API status = false")

    return data


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except:
        return None


def prepare_rows(club_id, sessions):
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


def save_sessions(club_id, sessions):
    if not sessions:
        return

    rows = prepare_rows(club_id, sessions)

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
    finally:
        conn.close()


def sync_sessions_incremental():
    logging.info("=== START DATE SYNC ===")

    today = datetime.now().date()
    date_from = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    clubs = get_clubs()

    for club in clubs:
        club_id = club["club_id"]
        api_key = club["lg_api_key"]
        secret = club["secret"]

        logging.info(f"Клуб {club_id} | {date_from} → {date_to}")

        page = 1

        while True:
            data = fetch_sessions(secret, api_key, page, date_from, date_to)

            sessions = data.get("data", [])
            total_pages = data.get("total_pages", 1)

            if not sessions:
                break

            save_sessions(club_id, sessions)

            logging.info(f"page {page}/{total_pages}: {len(sessions)}")

            if page >= total_pages:
                break

            page += 1

    logging.info("=== END SYNC ===")


if __name__ == "__main__":
    sync_sessions_incremental()