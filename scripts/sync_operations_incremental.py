import argparse
import hashlib
import logging
import re
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

SUM_FROM = 1
SUM_TO = 100000
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


def fetch_operations(secret: str, api_key: str, club_id: int, date_from: str, date_to: str):
    url = f"https://{secret}.langame.ru/public_api/all_operations_log/list"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    params = {
        "date_from": date_from,
        "date_to": date_to,
        "sum_from": SUM_FROM,
        "sum_to": SUM_TO
    }

    response = httpx.get(url, headers=headers, params=params, timeout=120)

    if response.status_code != 200:
        raise Exception(f"Ошибка API: {response.status_code} {response.text}")

    json_data = response.json()

    if not json_data.get("status"):
        raise Exception("API вернул status = false")

    return json_data.get("data", [])


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def extract_phone(operation_name: str):
    if not operation_name:
        return None

    match = re.search(r"\((\d{10,15})\)", operation_name)
    if match:
        return match.group(1)

    return None


def build_operation_uid(club_id: int, operation: dict) -> str:
    raw = "|".join([
        str(club_id),
        str(operation.get("date_normal") or ""),
        str(operation.get("type") or ""),
        str(operation.get("name") or ""),
        str(operation.get("source") or ""),
        str(operation.get("form") or ""),
        str(operation.get("sum") or ""),
        str(operation.get("date_fiscal") or ""),
        str(operation.get("fn_number") or ""),
        str(operation.get("fiscal_number") or "")
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_rows(club_id: int, operations: list):
    rows = []
    now = datetime.utcnow()

    for op in operations:
        rows.append((
            build_operation_uid(club_id, op),
            club_id,
            op.get("club_name"),
            op.get("type"),
            op.get("name"),
            extract_phone(op.get("name")),
            op.get("source"),
            op.get("form"),
            op.get("sum"),
            parse_datetime(op.get("date_normal")),
            op.get("date"),
            op.get("time"),
            parse_datetime(op.get("date_fiscal")),
            op.get("fn_number"),
            op.get("fiscal_number"),
            now,
            now,
        ))

    return rows


def save_operations(club_id: int, operations: list):
    if not operations:
        return 0

    rows = prepare_rows(club_id, operations)

    sql = """
        INSERT INTO operations_log (
            operation_uid,
            club_id,
            club_name,
            type,
            name,
            phone,
            source,
            form,
            sum,
            date_normal,
            date,
            time,
            date_fiscal,
            fn_number,
            fiscal_number,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            club_name = VALUES(club_name),
            type = VALUES(type),
            name = VALUES(name),
            phone = VALUES(phone),
            source = VALUES(source),
            form = VALUES(form),
            sum = VALUES(sum),
            date_normal = VALUES(date_normal),
            date = VALUES(date),
            time = VALUES(time),
            date_fiscal = VALUES(date_fiscal),
            fn_number = VALUES(fn_number),
            fiscal_number = VALUES(fiscal_number),
            updated_at = VALUES(updated_at)
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
        conn.commit()
        logging.info(f"Сохранено операций: {len(rows)}")
        return len(rows)
    finally:
        conn.close()


def sync_operations_incremental(club_id=None):
    logging.info("=== START OPERATIONS SYNC ===")

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
        lock = job_lock("sync_operations_incremental", club_id=current_club_id, ttl_minutes=60)
        acquired_lock = lock.__enter__()
        job_run_id = start_job_run(
            "sync_operations_incremental",
            club_id=current_club_id,
            metadata={"source": "langame", "date_from": date_from, "date_to": date_to},
        )
        if not acquired_lock.acquired:
            finish_job_run(
                job_run_id,
                "skipped_locked",
                metadata={"reason": "sync_operations_incremental already running"},
            )
            summary.append({"club_id": current_club_id, "skipped": "locked", "date_from": date_from, "date_to": date_to})
            lock.__exit__(None, None, None)
            continue

        logging.info(f"Клуб {current_club_id} | Langame secret={secret} | {date_from} → {date_to}")

        try:
            operations = fetch_operations(secret, api_key, current_club_id, date_from, date_to)
            logging.info(f"Получено операций: {len(operations)}")

            saved = save_operations(current_club_id, operations)
            finish_job_run(
                job_run_id,
                "success",
                rows_received=len(operations),
                rows_saved=saved,
                metadata={"date_from": date_from, "date_to": date_to},
            )
            summary.append({"club_id": current_club_id, "received": len(operations), "saved": saved, "date_from": date_from, "date_to": date_to})
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            raise
        finally:
            lock.__exit__(None, None, None)

    logging.info("=== END OPERATIONS SYNC ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental sync operations from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    args = parser.parse_args()
    sync_operations_incremental(args.club_id)
