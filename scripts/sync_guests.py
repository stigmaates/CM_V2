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
        autocommit=False
    )


def get_club_data(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            service_enabled_expr = service_enabled_select_expr(cursor)
            cursor.execute("""
                SELECT club_id, lg_api_key, secret, {service_enabled_expr}
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
            """.format(service_enabled_expr=service_enabled_expr), (club_id,))
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


def fetch_guests(secret: str, api_key: str):
    """Fetch all guest pages from Langame.

    Important: /guests/list returns only 10 rows by default if page_limit is not
    passed, so we must explicitly paginate.
    """

    url = f"https://{secret}.langame.ru/public_api/guests/list"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    all_guests = []
    page = 1

    while True:
        params = {
            "page": page,
            "page_limit": PAGE_LIMIT,
        }

        response = httpx.get(url, headers=headers, params=params, timeout=120)

        if response.status_code != 200:
            raise Exception(f"Ошибка API: {response.status_code} {response.text}")

        json_data = response.json()

        if not json_data.get("status"):
            raise Exception("API вернул status = false")

        guests = json_data.get("data", []) or []
        total_pages = int(json_data.get("total_pages") or 0)

        logging.info(
            f"Langame guests page {page}"
            + (f"/{total_pages}" if total_pages else "")
            + f": {len(guests)}"
        )

        all_guests.extend(guests)

        if total_pages:
            if page >= total_pages:
                break
        else:
            if len(guests) < PAGE_LIMIT:
                break

        if not guests:
            break

        page += 1

    return all_guests


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def prepare_guests_data(club_id: int, guests: list):
    rows = []

    for g in guests:
        rows.append((
            g.get("guest_id"),
            club_id,
            g.get("phone"),
            g.get("fio"),
            parse_date(g.get("birthday")),
            parse_datetime(g.get("date_insert")),
            g.get("gender")
        ))

    return rows


def save_guests(club_id: int, guests: list):
    if not guests:
        logging.info("Нет гостей для сохранения")
        return

    rows = prepare_guests_data(club_id, guests)

    sql = """
        INSERT INTO guests (
            guest_id,
            club_id,
            phone,
            fio,
            birth_date,
            date_insert,
            created_at,
            gender
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
        ON DUPLICATE KEY UPDATE
            phone = VALUES(phone),
            fio = VALUES(fio),
            birth_date = VALUES(birth_date),
            date_insert = VALUES(date_insert),
            gender = VALUES(gender)
    """

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
        conn.commit()
        logging.info(f"Сохранено/обновлено гостей: {len(rows)}")
    finally:
        conn.close()


def sync_guests(club_id: int):
    logging.info(f"Синхронизация гостей для клуба {club_id}")

    club = get_club_data(club_id)

    if not club:
        raise Exception(f"Клуб {club_id} не найден")

    if not is_service_enabled(club):
        logging.info("Клуб %s выключен, initial sync гостей пропущен", club_id)
        return {"club_id": club_id, "status": "skipped_disabled"}

    api_key = club["lg_api_key"]
    secret = club["secret"]

    logging.info("Клуб %s | Langame guests initial sync", club_id)

    guests = fetch_guests(secret, api_key)

    logging.info(f"Получено гостей из API: {len(guests)}")

    save_guests(club_id, guests)

    logging.info(f"Синхронизация гостей клуба {club_id} завершена")
    return {"club_id": club_id, "status": "success", "received": len(guests), "saved": len(guests)}


def sync_all_guests():
    logging.info("=== START INITIAL GUEST SYNC FOR ALL CLUBS ===")
    clubs = get_clubs()
    for club in clubs:
        sync_guests(int(club["club_id"]))
    logging.info("=== END INITIAL GUEST SYNC FOR ALL CLUBS ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initial sync guests from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()

    if args.club_id:
        sync_guests(args.club_id)
    else:
        sync_all_guests()
