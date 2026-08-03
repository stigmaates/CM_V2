"""Cron helper: process referral rewards for all clubs."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run
from app.services.referrals import ensure_referral_tables, process_referral_rewards
from scripts.sync_utils import table_has_column


def main() -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            if table_has_column(cursor, "clubs", "service_enabled"):
                cursor.execute("SELECT club_id FROM clubs WHERE COALESCE(service_enabled, 1) = 1")
            else:
                cursor.execute("SELECT club_id FROM clubs")
            clubs = [int(row["club_id"]) for row in cursor.fetchall() or []]
        conn.commit()
    finally:
        conn.close()

    total = 0
    for club_id in clubs:
        lock = job_lock("process_referrals", club_id=club_id, ttl_minutes=30)
        acquired_lock = lock.__enter__()
        job_run_id = start_job_run("process_referrals", club_id=club_id)
        if not acquired_lock.acquired:
            finish_job_run(job_run_id, "skipped_locked", metadata={"reason": "referrals already running"})
            print(f"SKIP: referrals club_id={club_id}, locked")
            lock.__exit__(None, None, None)
            continue
        try:
            awarded = process_referral_rewards(club_id)
            total += awarded
            finish_job_run(job_run_id, "success", rows_received=awarded, rows_saved=awarded)
            print(f"OK: referrals club_id={club_id}, awarded={awarded}")
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            print(f"ERROR: referrals club_id={club_id}: {exc}")
            raise
        finally:
            lock.__exit__(None, None, None)
    print(f"OK: referrals processed, clubs={len(clubs)}, awarded_total={total}")


if __name__ == "__main__":
    main()
