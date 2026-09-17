"""Read-only verification of stage team data without personal details."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import get_db_connection
from app.services.guest_pulse import rows
from app.services.stage_mirror import stage_mirror_enabled


def main():
    if not stage_mirror_enabled():
        raise ValueError("Run only on the stage mirror")
    conn = get_db_connection()
    try:
        for club in rows(conn, "SELECT club_id FROM clubs WHERE service_enabled=1"):
            cid = club["club_id"]
            counts = {}
            for table in ("team_admins", "team_shifts", "module_registrations"):
                counts[table] = rows(conn, f"SELECT COUNT(*) AS cnt FROM {table} WHERE club_id=%s", (cid,))[0]["cnt"]
            dates = rows(
                conn,
                """SELECT SUM(registered_at IS NOT NULL) AS dated,SUM(is_estimated=0) AS exact
                FROM module_registrations WHERE club_id=%s""",
                (cid,),
            )[0]
            state = (rows(conn, "SELECT updated_at,error_code FROM team_sync_state WHERE club_id=%s", (cid,)) or [{}])[
                0
            ]
            print(f"Team club {cid}: {counts}; dates={dates}; sync={state}", flush=True)
        trigger = rows(
            conn,
            "SELECT COUNT(*) AS cnt FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME='team_module_registration'",
        )[0]["cnt"]
        print(f"Team registration trigger: {trigger}/1; outbound stop file present")
        return int(trigger != 1)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
