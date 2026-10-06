"""Build a stage-only Gizmo preview from data already imported; no API calls."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import get_db_connection
from app.integrations.stage import require_stage_environment
from app.services.guest_pulse import refresh_club


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int, required=True)
    args = parser.parse_args()
    require_stage_environment()
    conn = get_db_connection()
    try:
        print("Расчёт пульса по уже загруженным визитам...", flush=True)
        result = refresh_club(conn, args.club_id, stage_gizmo_preview=True)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["status"] != "updated":
            return 1
        print("Пульс готов. Обслуживание клуба остаётся выключенным.", flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc) if isinstance(exc, ValueError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
