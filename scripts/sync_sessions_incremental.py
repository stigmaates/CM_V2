import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pymysql
from pymysql.cursors import DictCursor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from app.services.job_locks import job_lock
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
        connect_timeout=DB_CONNECT_TIMEOUT,
        read_timeout=DB_READ_TIMEOUT,
        write_timeout=DB_WRITE_TIMEOUT,
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
        raise Exception(f"Ошибка API: {response.status_code} {response.text}")

    data = response.json()

    if not data.get("status"):
        raise Exception("API status = false")

    return data


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
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
        return 0

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
        return len(rows)
    finally:
        conn.close()


def sync_sessions_incremental(club_id=None):
    logging.info("=== START DATE SYNC ===")

    today = datetime.now().date()
    date_from = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    clubs = get_clubs(club_id)
    if club_id is not None and not clubs:
        raise Exception(f"Клуб {club_id} не найден")

    summary = []

    for club in clubs:
        current_club_id = int(club["club_id"])
        api_key = club["lg_api_key"]
        secret = club["secret"]
        lock = job_lock("sync_sessions_incremental", club_id=current_club_id, ttl_minutes=60)
        acquired_lock = lock.__enter__()
        job_run_id = start_job_run(
            "sync_sessions_incremental",
            club_id=current_club_id,
            metadata={"source": "langame", "date_from": date_from, "date_to": date_to},
        )
        if not acquired_lock.acquired:
            finish_job_run(
                job_run_id,
                "skipped_locked",
                metadata={"reason": "sync_sessions_incremental already running"},
            )
            summary.append({"club_id": current_club_id, "skipped": "locked", "date_from": date_from, "date_to": date_to})
            lock.__exit__(None, None, None)
            continue

        logging.info(f"Клуб {current_club_id} | Langame secret={secret} | {date_from} → {date_to}")

        try:
            page = 1
            total_saved = 0
            total_received = 0

            while True:
                data = fetch_sessions(secret, api_key, page, date_from, date_to)

                sessions = data.get("data", [])
                total_pages = data.get("total_pages", 1)

                if not sessions:
                    break

                total_received += len(sessions)
                saved = save_sessions(current_club_id, sessions)
                total_saved += saved

                logging.info(f"Клуб {current_club_id} | page {page}/{total_pages}: {len(sessions)} | сохранено: {saved}")

                if page >= total_pages:
                    break

                page += 1

            finish_job_run(
                job_run_id,
                "success",
                rows_received=total_received,
                rows_saved=total_saved,
                metadata={"date_from": date_from, "date_to": date_to},
            )
            summary.append({"club_id": current_club_id, "saved": total_saved, "date_from": date_from, "date_to": date_to})
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            raise
        finally:
            lock.__exit__(None, None, None)

    logging.info("=== END SYNC ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental sync sessions from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()
    sync_sessions_incremental(args.club_id)
