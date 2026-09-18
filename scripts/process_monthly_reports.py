"""Process queued monthly reports under a supervised systemd service."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection  # noqa: E402
from app.services.monthly_report_generation import generate_saved_monthly_report  # noqa: E402


def claimable_report_ids(limit: int) -> list[int]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE monthly_reports
                SET status='queued',error_message='Повтор после прерванной фоновой генерации'
                WHERE status='running'
                  AND generated_at < UTC_TIMESTAMP() - INTERVAL 30 MINUTE
                """
            )
            cursor.execute(
                """
                SELECT id
                FROM monthly_reports
                WHERE status='queued'
                ORDER BY generated_at,id
                LIMIT %s
                """,
                (limit,),
            )
            report_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.commit()
        return report_ids
    finally:
        conn.close()


def process_monthly_reports(limit: int) -> tuple[int, int]:
    completed = 0
    failed = 0
    for report_id in claimable_report_ids(limit):
        if generate_saved_monthly_report(report_id):
            completed += 1
        else:
            failed += 1
    return completed, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process queued monthly PDF reports.")
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 20:
        parser.error("--limit must be between 1 and 20")

    completed, failed = process_monthly_reports(args.limit)
    print(f"Monthly reports processed: completed={completed}, failed={failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
