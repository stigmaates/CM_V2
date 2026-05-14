import hashlib
import logging
import re
from datetime import datetime, timedelta

import httpx
import pymysql
from pymysql.cursors import DictCursor

from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


logging.basicConfig(level=logging.INFO)

SUM_FROM = 0
SUM_TO = 100000
CHUNK_DAYS = 7


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


def fetch_operations(secret: str, api_key: str, club_id: int, date_from: str, date_to: str):
    url = f"https://{secret}.langame.ru/public_api/all_operations_log/list"

    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key.strip()
    }

    params = {
        "date_from": date_from,
        "date_to": date_to,
        "club_id": club_id,
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
            datetime.utcnow(),
            datetime.utcnow(),
        ))

    return rows


def save_operations(club_id: int, operations: list):
    if not operations:
        return

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
    finally:
        conn.close()


def daterange_chunks(start_date: datetime.date, end_date: datetime.date, chunk_days: int):
    current_start = start_date

    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
        yield current_start, current_end
        current_start = current_end + timedelta(days=1)


def sync_operations_initial(club_id: int, date_from: str, date_to: str):
    logging.info(f"Старт initial sync операций для клуба {club_id}")

    club = get_club_data(club_id)
    if not club:
        raise Exception("Клуб не найден")

    api_key = club["lg_api_key"]
    secret = club["secret"]

    start_date = datetime.strptime(date_from, "%d.%m.%Y").date()
    end_date = datetime.strptime(date_to, "%d.%m.%Y").date()

    for chunk_start, chunk_end in daterange_chunks(start_date, end_date, CHUNK_DAYS):
        chunk_from = chunk_start.strftime("%d.%m.%Y")
        chunk_to = chunk_end.strftime("%d.%m.%Y")

        logging.info(f"Клуб {club_id} | {chunk_from} → {chunk_to}")

        operations = fetch_operations(secret, api_key, club_id, chunk_from, chunk_to)
        logging.info(f"Получено операций: {len(operations)}")

        save_operations(club_id, operations)

    logging.info("Initial sync операций завершен")

if __name__ == "__main__":
    today = datetime.now().date()

    sync_operations_initial(
        club_id=1,
        date_from="01.01.2026",
        date_to=today.strftime("%d.%m.%Y")
    )
