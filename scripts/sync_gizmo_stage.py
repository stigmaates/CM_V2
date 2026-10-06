"""Synchronize all available Gizmo history for an explicitly configured stage pilot."""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import get_db_connection
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_sync import synchronize
from app.integrations.stage import require_stage_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int, required=True)
    args = parser.parse_args()
    require_stage_environment()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = get_db_connection()
    try:
        result = synchronize(conn, args.club_id)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, (GizmoError, ValueError)) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
