import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run
from app.services.topup_bonuses import process_topup_bonus_awards
from scripts.process_mailings import tg_request

logging.basicConfig(level=logging.INFO)


def _send_message(telegram_id: int, text: str) -> tuple[bool, str | None]:
    try:
        response = tg_request(
            "sendMessage",
            {
                "chat_id": telegram_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        payload = response.json()
        if response.status_code == 200 and payload.get("ok") is True:
            return True, None
        return False, response.text[:1000]
    except Exception as exc:
        return False, str(exc)[:1000]


def _enabled_club_ids(club_id: int | None = None) -> list[int]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT s.club_id
                FROM club_topup_bonus_settings s
                JOIN clubs c ON c.club_id = s.club_id
                WHERE s.is_enabled = 1 AND c.service_enabled = 1
            """
            params = []
            if club_id is not None:
                sql += " AND s.club_id = %s"
                params.append(club_id)
            sql += " ORDER BY s.club_id"
            cursor.execute(sql, params)
            return [int(row["club_id"]) for row in cursor.fetchall()]
    finally:
        conn.close()


def process_topup_bonuses(club_id: int | None = None) -> list[dict]:
    summary = []
    for current_club_id in _enabled_club_ids(club_id):
        with job_lock("process_topup_bonuses", club_id=current_club_id, ttl_minutes=10) as lock:
            if not lock.acquired:
                continue
            job_id = start_job_run("process_topup_bonuses", club_id=current_club_id)
            try:
                result = process_topup_bonus_awards(current_club_id, send_message=_send_message)
                finish_job_run(
                    job_id,
                    "success",
                    rows_received=result["awarded"],
                    rows_saved=result["awarded"],
                    metadata=result,
                )
                summary.append({"club_id": current_club_id, **result})
            except Exception as exc:
                finish_job_run(job_id, "error", error_text=str(exc))
                logging.exception("Ошибка обработки бонусов за пополнения клуба %s", current_club_id)
                summary.append({"club_id": current_club_id, "error": str(exc)})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Award Cyber Bonus rewards for Langame topups")
    parser.add_argument("--club-id", type=int, help="Process one internal club_id")
    args = parser.parse_args()
    print(process_topup_bonuses(args.club_id))
