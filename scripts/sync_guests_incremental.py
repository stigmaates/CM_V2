import logging
from datetime import datetime, timedelta

import httpx
import pymysql
from pymysql.cursors import DictCursor

from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


logging.basicConfig(level=logging.INFO)


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


def get_existing_guest_ids(club_id):
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


def fetch_guests(secret, api_key):
    url = f"https://{secret}.langame.ru/public_api/guests/list"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    response = httpx.get(url, headers=headers, timeout=60)

    data = response.json()

    if not data.get("status"):
        raise Exception("API status = false")

    return data.get("data", [])


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except:
        return None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except:
        return None


def filter_new_guests(guests, existing_ids):
    result = []

    threshold = datetime.now() - timedelta(days=1)

    for g in guests:
        guest_id = g.get("guest_id")

        if guest_id not in existing_ids:
            result.append(g)
            continue

        # если уже есть — можно пропустить
        # либо обновлять только свежих
        date_insert = parse_datetime(g.get("date_insert"))

        if date_insert and date_insert >= threshold:
            result.append(g)

    return result


def prepare_rows(club_id, guests):
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


def save_guests(club_id, guests):
    if not guests:
        return

    rows = prepare_rows(club_id, guests)

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
    finally:
        conn.close()


def sync_guests_incremental():
    logging.info("=== START GUEST SYNC ===")

    clubs = get_clubs()

    for club in clubs:
        club_id = club["club_id"]
        api_key = club["lg_api_key"]
        secret = club["secret"]

        logging.info(f"Клуб {club_id}")

        existing_ids = get_existing_guest_ids(club_id)

        guests = fetch_guests(secret, api_key)

        filtered = filter_new_guests(guests, existing_ids)

        logging.info(f"Получено: {len(guests)} | к обновлению: {len(filtered)}")

        save_guests(club_id, filtered)

    logging.info("=== END ===")


if __name__ == "__main__":
    sync_guests_incremental()