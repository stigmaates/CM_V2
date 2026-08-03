import argparse
import logging
from datetime import datetime

import httpx
import pymysql
from pymysql.cursors import DictCursor

from app.config import (
    DB_CONNECT_TIMEOUT,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_READ_TIMEOUT,
    DB_USER,
    DB_WRITE_TIMEOUT,
)
from scripts.sync_utils import is_service_enabled, service_enabled_select_expr

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
        connect_timeout=DB_CONNECT_TIMEOUT,
        read_timeout=DB_READ_TIMEOUT,
        write_timeout=DB_WRITE_TIMEOUT,
        autocommit=False,
    )


def get_club_data(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            service_enabled_expr = service_enabled_select_expr(cursor)
            cursor.execute(
                """
                SELECT club_id, lg_api_key, secret, {service_enabled_expr}
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
            """.format(service_enabled_expr=service_enabled_expr),
                (club_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_clubs():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            service_enabled_expr = service_enabled_select_expr(cursor)
            cursor.execute("""
                SELECT club_id, lg_api_key, secret, {service_enabled_expr}
                FROM clubs
                ORDER BY club_id
            """.format(service_enabled_expr=service_enabled_expr))
            return cursor.fetchall()
    finally:
        conn.close()


def get_existing_guest_ids(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT guest_id
                FROM guests
                WHERE club_id = %s
            """,
                (club_id,),
            )
            return {row["guest_id"] for row in cursor.fetchall()}
    finally:
        conn.close()


def fetch_sessions_page(secret: str, api_key: str, page: int):
    url = f"https://{secret}.langame.ru/public_api/guests/sessions"

    headers = {"accept": "application/json", "X-API-KEY": api_key.strip()}

    params = {"page_limit": PAGE_LIMIT, "page": page}

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
    except Exception:
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
        rows.append(
            (
                s.get("id"),
                club_id,
                s.get("UUID"),
                s.get("guest_id"),
                parse_datetime(s.get("date_start")),
                parse_datetime(s.get("date_stop")),
            )
        )

    return rows


def save_sessions(club_id: int, sessions: list):
    if not sessions:
        return 0

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
        return len(rows)
    finally:
        conn.close()


def sync_sessions_initial(club_id: int):
    logging.info(f"Старт initial sync сессий для клуба {club_id}")

    club = get_club_data(club_id)
    if not club:
        raise Exception(f"Клуб {club_id} не найден")

    if not is_service_enabled(club):
        logging.info("Клуб %s выключен, initial sync сессий пропущен", club_id)
        return {"club_id": club_id, "status": "skipped_disabled", "saved": 0, "skipped": 0}

    api_key = club["lg_api_key"]
    secret = club["secret"]

    logging.info("Клуб %s | Langame sessions initial sync", club_id)

    existing_guest_ids = get_existing_guest_ids(club_id)
    logging.info(f"Загружено гостей: {len(existing_guest_ids)}")

    first_page = fetch_sessions_page(secret, api_key, page=1)

    total_pages = first_page.get("total_pages", 0)
    sessions = first_page.get("data", [])

    logging.info(f"Всего страниц: {total_pages}")

    total_saved = 0
    total_skipped = 0

    filtered, skipped = filter_sessions(sessions, existing_guest_ids)
    total_skipped += skipped
    logging.info(f"Страница 1: {len(filtered)} сохранено, {skipped} пропущено")
    total_saved += save_sessions(club_id, filtered)

    for page in range(2, total_pages + 1):
        data = fetch_sessions_page(secret, api_key, page=page)
        sessions = data.get("data", [])

        filtered, skipped = filter_sessions(sessions, existing_guest_ids)
        total_skipped += skipped

        logging.info(f"Страница {page}/{total_pages}: {len(filtered)} сохранено, {skipped} пропущено")
        total_saved += save_sessions(club_id, filtered)

    logging.info(f"Initial sync сессий клуба {club_id} завершен. Сохранено: {total_saved}, пропущено: {total_skipped}")
    return {"club_id": club_id, "saved": total_saved, "skipped": total_skipped}


def sync_all_sessions_initial():
    logging.info("=== START INITIAL SESSIONS SYNC FOR ALL CLUBS ===")
    summary = []
    for club in get_clubs():
        summary.append(sync_sessions_initial(int(club["club_id"])))
    logging.info("=== END INITIAL SESSIONS SYNC FOR ALL CLUBS ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initial sync sessions from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()

    if args.club_id:
        sync_sessions_initial(args.club_id)
    else:
        sync_all_sessions_initial()
