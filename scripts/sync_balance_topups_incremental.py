import argparse
import logging
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
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
LOOKBACK_DAYS = 2


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


def get_clubs(club_id=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if club_id is None:
                cursor.execute(
                    """
                    SELECT club_id, lg_api_key, secret
                    FROM clubs
                    ORDER BY club_id
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT club_id, lg_api_key, secret
                    FROM clubs
                    WHERE club_id = %s
                    ORDER BY club_id
                    """,
                    (club_id,),
                )
            return cursor.fetchall()
    finally:
        conn.close()


def fetch_topups_page(secret: str, api_key: str, page: int, date_from: str, date_to: str):
    url = f"https://{secret}.langame.ru/public_api/balances/list"
    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip(),
    }
    params = {
        "page_limit": PAGE_LIMIT,
        "page": page,
        "date_from": date_from,
        "date_to": date_to,
    }

    response = httpx.get(url, headers=headers, params=params, timeout=120)
    if response.status_code != 200:
        raise Exception(f"Ошибка API: {response.status_code} {response.text}")

    data = response.json()
    if not data.get("status"):
        raise Exception("API вернул status = false")
    return data


def fetch_topups(secret: str, api_key: str, date_from: str, date_to: str):
    all_topups = []
    page = 1
    total_pages = None

    while True:
        data = fetch_topups_page(secret, api_key, page, date_from, date_to)
        rows = data.get("data", []) or []
        all_topups.extend(rows)

        total_pages = data.get("total_pages") or total_pages
        logging.info(
            "Langame secret=%s | balance topups page %s%s: %s",
            secret,
            page,
            f"/{total_pages}" if total_pages else "",
            len(rows),
        )

        if total_pages is not None and page >= int(total_pages):
            break
        if len(rows) < PAGE_LIMIT:
            break
        page += 1

    return all_topups


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def parse_amount(value) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def normalize_phone(phone):
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return digits or None


def prepare_rows(club_id: int, topups: list):
    rows = []
    now = datetime.utcnow()
    for item in topups:
        topup_at = parse_datetime(item.get("date"))
        if not item.get("id") or not item.get("guest_id") or not topup_at:
            continue
        rows.append(
            (
                club_id,
                item.get("id"),
                item.get("guest_id"),
                item.get("guest_name"),
                normalize_phone(item.get("phone")),
                parse_amount(item.get("amount")),
                topup_at,
                now,
                now,
            )
        )
    return rows


def save_topups(club_id: int, topups: list):
    rows = prepare_rows(club_id, topups)
    if not rows:
        return 0

    sql = """
        INSERT INTO guest_balance_topups (
            club_id,
            topup_id,
            guest_id,
            guest_name,
            phone,
            amount,
            topup_at,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            guest_id = VALUES(guest_id),
            guest_name = VALUES(guest_name),
            phone = VALUES(phone),
            amount = VALUES(amount),
            topup_at = VALUES(topup_at),
            updated_at = VALUES(updated_at)
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
        conn.commit()
        logging.info("Сохранено пополнений баланса: %s", len(rows))
        return len(rows)
    finally:
        conn.close()


def sync_balance_topups_incremental(club_id=None):
    logging.info("=== START BALANCE TOPUPS SYNC ===")

    today = datetime.now().date()
    date_from = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    clubs = get_clubs(club_id)
    if club_id is not None and not clubs:
        raise Exception(f"Клуб {club_id} не найден")

    summary = []

    for club in clubs:
        current_club_id = int(club["club_id"])
        api_key = club["lg_api_key"]
        secret = club["secret"]
        lock = job_lock("sync_balance_topups_incremental", club_id=current_club_id, ttl_minutes=60)
        acquired_lock = lock.__enter__()
        job_run_id = start_job_run(
            "sync_balance_topups_incremental",
            club_id=current_club_id,
            metadata={"source": "langame", "date_from": date_from, "date_to": date_to},
        )
        if not acquired_lock.acquired:
            finish_job_run(
                job_run_id,
                "skipped_locked",
                metadata={"reason": "sync_balance_topups_incremental already running"},
            )
            summary.append({"club_id": current_club_id, "skipped": "locked", "date_from": date_from, "date_to": date_to})
            lock.__exit__(None, None, None)
            continue

        logging.info("Клуб %s | Langame secret=%s | %s -> %s", current_club_id, secret, date_from, date_to)

        try:
            topups = fetch_topups(secret, api_key, date_from, date_to)
            saved = save_topups(current_club_id, topups)
            finish_job_run(
                job_run_id,
                "success",
                rows_received=len(topups),
                rows_saved=saved,
                metadata={"date_from": date_from, "date_to": date_to},
            )
            summary.append({"club_id": current_club_id, "received": len(topups), "saved": saved, "date_from": date_from, "date_to": date_to})
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            raise
        finally:
            lock.__exit__(None, None, None)

    logging.info("=== END BALANCE TOPUPS SYNC ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental sync guest balance topups from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()
    sync_balance_topups_incremental(args.club_id)
