"""Import recent game matches and update active weekly contracts."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.game_contracts import process_active_contracts
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run


def main() -> None:
    with job_lock("process_game_contracts", ttl_minutes=30) as lock:
        job_run_id = start_job_run("process_game_contracts")
        if not lock.acquired:
            finish_job_run(job_run_id, "skipped_locked", metadata={"reason": "already running"})
            print("SKIP: game contracts already running")
            return
        try:
            result = process_active_contracts()
            status = "success" if not result["errors"] else "partial"
            finish_job_run(
                job_run_id,
                status,
                rows_received=result["matches"],
                rows_saved=result["completed"],
                metadata=result,
            )
            print(
                "OK: game contracts processed, "
                f"targets={result['guests']}, matches={result['matches']}, "
                f"completed={result['completed']}, errors={result['errors']}"
            )
        except Exception as exc:
            finish_job_run(job_run_id, "error", error_text=str(exc))
            raise


if __name__ == "__main__":
    main()
