import argparse
import logging
from datetime import datetime, timedelta

import httpx
import pymysql
from pymysql.cursors import DictCursor

from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
from app.services.job_runs import finish_job_run, start_job_run


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


def get_clubs(club_id=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if club_id is None:
                cursor.execute("""
                    SELECT club_id, lg_api_key, secret
                    FROM clubs
                    ORDER BY club_id
                """)
            else:
                cursor.execute("""
                    SELECT club_id, lg_api_key, secret
                    FROM clubs
                    WHERE club_id = %s
                    ORDER BY club_id
                """, (club_id,))
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
            raise Exception("API status = false")

        guests = json_data.get("data", []) or []
        total_pages = int(json_data.get("total_pages") or 0)

        logging.info(
            f"Langame secret={secret} | guests page {page}"
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


def filter_new_guests(guests, existing_ids):
    result = []
    threshold = datetime.now() - timedelta(days=1)

    for g in guests:
        guest_id = g.get("guest_id")

        if guest_id not in existing_ids:
            result.append(g)
            continue

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
        return 0

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
        return len(rows)
    finally:
        conn.close()


def sync_guests_incremental(club_id=None):
    logging.info("=== START GUEST SYNC ===")

    clubs = get_clubs(club_id)
    if club_id is not None and not clubs:
        raise Exception(f"Клуб {club_id} не найден")

    summary = []

    for club in clubs:
        current_club_id = int(club["club_id"])
        api_key = club["lg_api_key"]
        secret = club["secret"]
        job_run_id = start_job_run(
            "sync_guests_incremental",
            club_id=current_club_id,
            metadata={"source": "langame"},
        )

        logging.info(f"Клуб {current_club_id} | Langame secret={secret}")

        try:
            existing_ids = get_existing_guest_ids(current_club_id)
            guests = fetch_guests(secret, api_key)
            filtered = filter_new_guests(guests, existing_ids)
            saved = save_guests(current_club_id, filtered)

            finish_job_run(
                job_run_id,
                "success",
                rows_received=len(guests),
                rows_saved=saved,
                metadata={"filtered": len(filtered)},
            )
            logging.info(f"Клуб {current_club_id} | получено: {len(guests)} | к обновлению: {len(filtered)} | сохранено: {saved}")
            summary.append({"club_id": current_club_id, "received": len(guests), "filtered": len(filtered), "saved": saved})
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            raise

    logging.info("=== END GUEST SYNC ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental sync guests from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()
    sync_guests_incremental(args.club_id)
