"""UTC wall-clock slots matching the production Langame cron (verified 2026-10-07)."""

from datetime import datetime

from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_normalize import external_id

INTERVAL_MINUTES = {"guests": 10, "sessions": 1, "topups": 3}


def components_due(settings, now):
    stamps = (settings.get("sync_checkpoint") or {}).get("component_success_at") or {}
    due = set()
    for part, minutes in INTERVAL_MINUTES.items():
        try:
            previous = datetime.fromisoformat(stamps[part])
            if previous.tzinfo is None:
                raise ValueError("Missing timezone")
            old_slot = int(previous.timestamp()) // (minutes * 60)
            new_slot = int(now.timestamp()) // (minutes * 60)
            if old_slot != new_slot:
                due.add(part)
        except (KeyError, TypeError, ValueError):
            due.add(part)
    return due


def read_references(conn, club_id):
    """Only source IDs are needed; never reread or rewrite cached personal details."""
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT guest_id FROM guests WHERE club_id=%s", (club_id,))
        guests = {external_id(row["guest_id"]) for row in cur.fetchall()}
        cur.execute("SELECT uuid FROM club_pc_names WHERE club_id=%s", (club_id,))
        hosts = set()
        for row in cur.fetchall():
            if not str(row["uuid"]).startswith("gizmo:"):
                raise GizmoError("Unexpected host namespace in Gizmo club")
            hosts.add(external_id(str(row["uuid"]).split(":", 1)[1]))
    conn.rollback()
    return {"guests": guests, "hosts": hosts}
