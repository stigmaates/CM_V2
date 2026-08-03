import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_balance_topups_incremental import (
    fetch_topups,
    get_clubs,
    save_topups,
)
from scripts.sync_utils import is_service_enabled

logging.basicConfig(level=logging.INFO)

CHUNK_DAYS = 7
DEFAULT_START_DATE = "2026-01-01"


def daterange_chunks(start_date, end_date, chunk_days: int):
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
        yield current_start, current_end
        current_start = current_end + timedelta(days=1)


def sync_balance_topups_initial(club_id: int, date_from: str, date_to: str):
    clubs = get_clubs(club_id)
    if not clubs:
        raise Exception(f"Клуб {club_id} не найден")
    club = clubs[0]

    if not is_service_enabled(club):
        logging.info("Клуб %s выключен, initial sync пополнений пропущен", club_id)
        return {
            "club_id": club_id,
            "status": "skipped_disabled",
            "received": 0,
            "saved": 0,
            "date_from": date_from,
            "date_to": date_to,
        }

    api_key = club["lg_api_key"]
    secret = club["secret"]
    start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
    end_date = datetime.strptime(date_to, "%Y-%m-%d").date()

    logging.info("Старт initial sync пополнений баланса для клуба %s", club_id)

    total_received = 0
    total_saved = 0
    for chunk_start, chunk_end in daterange_chunks(start_date, end_date, CHUNK_DAYS):
        chunk_from = chunk_start.strftime("%Y-%m-%d")
        chunk_to = chunk_end.strftime("%Y-%m-%d")
        logging.info("Клуб %s | %s -> %s", club_id, chunk_from, chunk_to)
        topups = fetch_topups(secret, api_key, chunk_from, chunk_to)
        total_received += len(topups)
        total_saved += save_topups(club_id, topups)

    logging.info(
        "Initial sync пополнений клуба %s завершен. Получено: %s. Сохранено: %s",
        club_id,
        total_received,
        total_saved,
    )
    return {
        "club_id": club_id,
        "received": total_received,
        "saved": total_saved,
        "date_from": date_from,
        "date_to": date_to,
    }


def sync_all_balance_topups_initial(date_from: str, date_to: str):
    summary = []
    for club in get_clubs():
        summary.append(sync_balance_topups_initial(int(club["club_id"]), date_from=date_from, date_to=date_to))
    return summary


if __name__ == "__main__":
    today = datetime.now().date().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="Initial sync guest balance topups from Langame")
    parser.add_argument("--club-id", type=int, help="Sync only one internal club_id. If omitted, sync all clubs.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Start date YYYY-MM-DD")
    parser.add_argument("--date-to", default=today, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    if args.club_id:
        sync_balance_topups_initial(args.club_id, date_from=args.date_from, date_to=args.date_to)
    else:
        sync_all_balance_topups_initial(date_from=args.date_from, date_to=args.date_to)
