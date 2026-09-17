"""Read-only post-deployment consistency check. Does not send messages or rewards."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import get_db_connection
from app.services.guest_pulse import rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int)
    args = parser.parse_args()
    conn = get_db_connection()
    try:
        club_filter = " AND c.club_id=%s" if args.club_id else ""
        params = (args.club_id,) if args.club_id else ()
        clubs = rows(
            conn,
            """SELECT c.club_id,p.calculated_at,p.snapshot_date,p.backfilled_at,p.guest_count
            FROM clubs c LEFT JOIN guest_pulse_clubs p ON p.club_id=c.club_id
            WHERE c.service_enabled=1""" + club_filter,
            params,
        )
        issues = []
        for club in clubs:
            cid = club["club_id"]
            current = rows(
                conn,
                """SELECT COUNT(*) AS cnt, SUM(health_score<0 OR health_score>100 OR value_score<0
                OR value_score>100 OR engagement_score<0 OR engagement_score>100) AS invalid
                FROM guest_pulse_current WHERE club_id=%s""",
                (cid,),
            )[0]
            history = rows(
                conn,
                """SELECT COUNT(DISTINCT snapshot_date) AS days, SUM(reconstructed) AS reconstructed
                FROM guest_score_history WHERE club_id=%s""",
                (cid,),
            )[0]
            if not club["calculated_at"] or not club["backfilled_at"] or current["invalid"]:
                issues.append(cid)
            print(
                f"Club {cid}: guests={current['cnt']}, history_days={history['days']}, updated_utc={club['calculated_at']}"
            )
        triggers = rows(
            conn,
            "SELECT COUNT(*) AS cnt FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME LIKE 'guest_pulse_%'",
        )[0]["cnt"]
        print(f"Guest Pulse source triggers: {triggers}/30")
        if issues or triggers != 30:
            print("Guest Pulse check FAILED", file=sys.stderr)
            return 1
        print("Guest Pulse check OK")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
