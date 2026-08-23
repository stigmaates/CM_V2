from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.cm_bonuses import retry_failed_cm_bonus_redeem_notifications
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retry failed КБ redeem Telegram notifications.")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    with job_lock("retry_cm_bonus_redeem_notifications", club_id=0, ttl_minutes=5) as lock:
        if not lock.acquired:
            print("SKIPPED: another retry worker is active")
            return 0

        job_id = start_job_run("retry_cm_bonus_redeem_notifications", club_id=0)
        try:
            result = retry_failed_cm_bonus_redeem_notifications(limit=args.limit)
            finish_job_run(
                job_id,
                "success",
                rows_received=result["selected"],
                rows_saved=result["sent"],
                metadata=result,
            )
        except Exception as exc:
            finish_job_run(job_id, "error", error_text=str(exc))
            raise

    print(
        "SUMMARY: "
        f"selected={result['selected']} "
        f"sent={result['sent']} "
        f"failed={result['failed']} "
        f"skipped={result['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
