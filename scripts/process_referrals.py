"""Cron helper: process referral rewards for all clubs."""
from __future__ import annotations

from app.core import get_db_connection
from app.services.referrals import ensure_referral_tables, process_referral_rewards


def main() -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute("SELECT club_id FROM clubs")
            clubs = [int(row["club_id"]) for row in cursor.fetchall() or []]
        conn.commit()
    finally:
        conn.close()

    total = 0
    for club_id in clubs:
        try:
            awarded = process_referral_rewards(club_id)
            total += awarded
            print(f"OK: referrals club_id={club_id}, awarded={awarded}")
        except Exception as exc:
            print(f"ERROR: referrals club_id={club_id}: {exc}")
            raise
    print(f"OK: referrals processed, clubs={len(clubs)}, awarded_total={total}")


if __name__ == "__main__":
    main()
