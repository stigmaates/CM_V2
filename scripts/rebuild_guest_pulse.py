"""Refresh dirty clubs and take one daily snapshot at/after 04:00 club-local time."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import get_db_connection
from app.services.guest_pulse import refresh_club, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int)
    parser.add_argument(
        "--backfill", action="store_true", help="Reconstruct missing past 30 days; never overwrite existing snapshots"
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    conn = get_db_connection()
    try:
        clubs = rows(
            conn,
            "SELECT club_id FROM clubs WHERE service_enabled=1" + (" AND club_id=%s" if args.club_id else ""),
            (args.club_id,) if args.club_id else (),
        )
    finally:
        conn.close()
    failed = False
    for club in clubs:
        conn = get_db_connection()
        try:
            print(refresh_club(conn, int(club["club_id"]), backfill=args.backfill, force=args.force), flush=True)
        except Exception as exc:
            # Exception SQL and payloads can contain private data; log only the class.
            print(f"Guest Pulse club {club['club_id']}: {type(exc).__name__}", file=sys.stderr, flush=True)
            failed = True
        finally:
            conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
