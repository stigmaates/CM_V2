"""Shared Gizmo scheduler: onboarding, active service and explicit paused refresh.

Production requires explicit runtime opt-in and isolated private state.
"""

from app.core import get_db_connection
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_runtime import require_gizmo_environment
from app.integrations.gizmo_sync import DIRECTORY, run_lock, synchronize


def configured_clubs(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.club_id FROM clubs c
            JOIN club_integrations i ON i.club_id = c.club_id
            WHERE c.integration_provider = 'gizmo'
              AND (c.service_enabled = 0 OR c.integration_ready = 1)
            ORDER BY c.club_id
        """)
        rows = cur.fetchall()
    conn.rollback()
    return [int(row["club_id"]) for row in rows]


def synchronize_due(*, directory=DIRECTORY):
    require_gizmo_environment(directory=directory)
    with run_lock(directory / "scheduler.lock"):
        conn = get_db_connection()
        try:
            club_ids = configured_clubs(conn)
        finally:
            conn.close()
        results = []
        for club_id in club_ids:
            if not (directory / f"sync-{club_id}.json").exists():
                continue  # No explicit preview opt-in yet.
            conn = None
            try:
                conn = get_db_connection()
                result = synchronize(conn, club_id, directory=directory, only_if_due=True)
                results.append({"club_id": club_id, "status": result["status"]})
            except Exception as exc:
                # One unavailable club cannot prevent the others from updating.
                results.append(
                    {
                        "club_id": club_id,
                        "status": "error",
                        "error": str(exc) if isinstance(exc, GizmoError) else type(exc).__name__,
                    }
                )
            finally:
                if conn is not None:
                    conn.close()
        return results
