"""Run configured Gizmo clubs in an explicitly enabled deployment."""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_runtime import require_gizmo_environment
from app.integrations.gizmo_scheduler import synchronize_due
from app.integrations.gizmo_sync import synchronize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-due", action="store_true")
    group.add_argument("--club-id", type=int)
    args = parser.parse_args()
    require_gizmo_environment()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.all_due:
        result = synchronize_due()
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if any(row["status"] == "error" for row in result):
            raise SystemExit(1)
        return
    conn = get_db_connection()
    try:
        print(json.dumps(synchronize(conn, args.club_id), ensure_ascii=False, indent=2), flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, (GizmoError, ValueError)) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
