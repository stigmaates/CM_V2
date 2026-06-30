from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.job_runs import mark_stale_job_runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Cyber Bonus background job runs.")
    parser.add_argument(
        "--max-running-minutes",
        type=int,
        default=60,
        help="Mark running jobs older than this many minutes as stale.",
    )
    args = parser.parse_args(argv)

    marked = mark_stale_job_runs(max_age_minutes=args.max_running_minutes)
    print(f"OK: stale background jobs marked={marked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
