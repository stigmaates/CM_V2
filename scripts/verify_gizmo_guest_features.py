"""Read-only stage checks of guest calculations against imported Gizmo sessions.

No API writes, notifications, awards or club activation. Every MySQL connection
is transaction-read-only, including connections opened by guest services.
"""

import argparse
import json
import sys
from collections import defaultdict
from contextlib import ExitStack
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.stage import require_stage_environment
from app.services import missions, reception, wheel


def readonly_connection():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute("SET SESSION MAX_EXECUTION_TIME=15000")
        return conn
    except BaseException:
        conn.close()
        raise


def verify(club_id, *, connection_factory=readonly_connection):
    require_stage_environment()
    report = dict(club_id=club_id, read_only=True, status="running", checked_at_utc=datetime.now(UTC).isoformat())
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT integration_provider,timezone,service_enabled,integration_ready FROM clubs WHERE club_id=%s",
                (club_id,),
            )
            club = cur.fetchone()
            if not club or club["integration_provider"] != "gizmo":
                raise ValueError("Select an existing Gizmo stage club")
            tz = ZoneInfo(club["timezone"])
            cur.execute(
                """SELECT s.guest_id,s.date_start,s.date_stop FROM guest_sessions s
                JOIN guests g ON g.club_id=s.club_id AND g.guest_id=s.guest_id
                WHERE s.club_id=%s AND s.date_start IS NOT NULL AND s.date_stop IS NOT NULL
                ORDER BY s.date_start DESC""",
                (club_id,),
            )
            rows = cur.fetchall()
            if not rows:
                raise ValueError("No personal sessions to verify")
            grouped = defaultdict(list)
            for row in rows:
                local = row["date_start"].replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None)
                grouped[row["guest_id"]].append(local)
            report["personal_sessions_read"] = len(rows)
            # Prefer guests with a UTC/local day boundary; cap database work.
            boundary_ids = {
                row["guest_id"]
                for row in rows
                if row["date_start"].date() != row["date_start"].replace(tzinfo=UTC).astimezone(tz).date()
            }
            candidates = sorted(grouped, key=lambda guest: (guest not in boundary_ids, guest))[:12]
            report["guests_checked"] = len(candidates)
            report["boundary_guests_checked"] = sum(guest in boundary_ids for guest in candidates)
            settings = dict(integration_provider="gizmo", club_timezone=club["timezone"])
            reception_checks = 0
            with ExitStack() as stack:
                for module in (missions, reception):
                    stack.enter_context(patch.object(module, "get_db_connection", connection_factory))
                for guest in candidates:
                    days = grouped[guest]
                    day = max(days).date()
                    start = datetime.combine(day, time.min)
                    end = start + timedelta(days=1) - timedelta(microseconds=1)
                    mission = dict(
                        settings,
                        target_metric="sessions_started_in_time_range_count",
                        start_at=start,
                        end_at=end,
                        config=dict(time_start="22:00", time_end="08:00"),
                    )
                    expected = sum(t.date() == day and (t.hour >= 22 or t.hour < 8) for t in days)
                    actual = missions.calculate_mission_progress(guest, club_id, mission)
                    if actual != expected:
                        raise ValueError("Night mission differs from source timestamps in club timezone")
                    expected_days = sorted({t.date() for t in days if t.date() >= day})
                    if wheel._get_visit_days(cur, guest, club_id, day, settings=settings) != expected_days:
                        raise ValueError("Visit streak dates differ from club-local dates")
                    cur.execute("SELECT phone FROM guests WHERE club_id=%s AND guest_id=%s", (club_id, guest))
                    phone = cur.fetchone()["phone"]
                    if not phone:
                        continue
                    variants = reception._phone_variants(phone)
                    if not variants:
                        continue
                    placeholders = ",".join(["%s"] * len(variants))
                    cur.execute(
                        f"SELECT COUNT(*) AS n FROM guests WHERE club_id=%s AND {reception.PHONE_NORMALIZED_SQL} IN ({placeholders})",
                        (club_id, *variants),
                    )
                    if cur.fetchone()["n"] != 1:
                        continue  # Shared telephone is not a unique identity.
                    lookup = reception.get_reception_guest_lookup(club_id=club_id, phone=phone)
                    if not lookup.get("found") or int(lookup["guest"]["guest_id"]) != guest:
                        raise ValueError("Reception lookup did not find the imported guest")
                    cur.execute("SELECT id FROM guest_prize_claims WHERE club_id=%s AND guest_id=%s", (club_id, guest))
                    if {r["id"] for r in cur.fetchall()} != {r["id"] for r in lookup["prize_claims"]}:
                        raise ValueError("Reception prize history differs from saved claims")
                    reception_checks += 1
            if not reception_checks:
                raise ValueError("No unique phone available for reception acceptance")
            report.update(
                status="complete",
                night_missions_match=True,
                local_streak_days_match=True,
                reception_guests_checked=reception_checks,
                club_flags=club,
                limitation="Read-only checks; does not exercise real Telegram delivery or award writes",
            )
            return report
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.club_id), ensure_ascii=False, indent=2))
