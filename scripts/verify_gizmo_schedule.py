"""Exercise separate resource writes on the existing disabled stage acceptance club."""

import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo import GizmoClient, GizmoError
from app.integrations.gizmo_import import save
from app.integrations.gizmo_incremental import checkpoint_valid, collect_sync
from app.integrations.gizmo_lifecycle import read_club
from app.integrations.gizmo_schedule import INTERVAL_MINUTES, read_references
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, read_target, run_lock
from app.integrations.stage import require_stage_environment
from app.services.guest_pulse import refresh_club
from scripts.rebuild_user_portrait import rebuild_club_portrait
from scripts.verify_gizmo_stage_lifecycle import TEST_NAME, totals


class TracedClient:
    def __init__(self, client):
        self.client = client
        self.calls = Counter()

    def get(self, resource, params=None):
        self.calls[resource if "/" not in resource else resource.split("/")[0] + "/detail"] += 1
        return self.client.get(resource, params)


def run():
    require_stage_environment()
    report = dict(status="running", started_at_utc=datetime.now(UTC).isoformat(), intervals_minutes=INTERVAL_MINUTES)
    conn = get_db_connection()
    try:
        with run_lock(DIRECTORY / "acceptance.lock"):
            manifest = private_json(DIRECTORY / "acceptance-incremental-900001.json")
            club_id = int(manifest["test_club_id"])
            if club_id == 900001:
                raise GizmoError("Test club must differ from source")
            club = read_club(conn, club_id)

            def check(candidate):
                if (
                    not candidate
                    or candidate.get("name") != TEST_NAME + " · обновления"
                    or candidate.get("owner_id") is not None
                    or candidate.get("service_enabled")
                    or candidate.get("integration_provider") != "gizmo"
                ):
                    raise GizmoError("Expected disabled isolated acceptance club")

            check(club)
            credentials = private_json(DIRECTORY / f"sync-{club_id}.json")
            if credentials.get("enabled") is not False:
                raise GizmoError("Test sync must remain paused")
            source = read_club(conn, 900001)
            source_flags = {key: source[key] for key in ("service_enabled", "integration_ready")}
            client = GizmoClient(
                **credentials["connection"],
                certificate_pem=credentials["certificate_pem"],
                api_key=credentials["api_key"],
            )
            with run_lock(DIRECTORY / f"sync-{club_id}.lock"):
                settings = read_target(conn, club_id, lifecycle=True)
                if not checkpoint_valid(settings.get("sync_checkpoint") or {}, datetime.now(UTC)):
                    raise GizmoError("Acceptance checkpoint is stale; refresh the isolated acceptance club first")
                report["club_id"] = club_id
                report["before"] = totals(conn, club_id)
                cycles = []
                for parts in ({"sessions"}, {"sessions", "topups"}, {"guests"}):
                    print("Проверяем отдельное обновление: " + ", ".join(sorted(parts)), flush=True)
                    api = TracedClient(client)
                    data = collect_sync(
                        api,
                        settings=settings,
                        end=datetime.now(UTC),
                        components=parts,
                        references=read_references(conn, club_id),
                    )
                    if data["scope"]["sync_mode"] != "incremental":
                        raise GizmoError("Unexpected full fallback during schedule verification")
                    if "guests" not in parts and (api.calls["users"] or api.calls["hosts"]):
                        raise GizmoError("Minute cycle reread full directories")
                    if "topups" not in parts and api.calls["deposittransactions"]:
                        raise GizmoError("Unscheduled deposits were requested")
                    if "sessions" not in parts and (api.calls["sessions"] or api.calls["usersessions"]):
                        raise GizmoError("Unscheduled sessions were requested")
                    data["scope"]["source"] = settings["source"]
                    before = totals(conn, club_id)
                    save(conn, club_id, data, target_check=check)
                    after = totals(conn, club_id)
                    if "topups" not in parts and any(
                        before[k] != after[k] for k in ("guest_balance_topups", "topups_amount")
                    ):
                        raise GizmoError("Unscheduled deposit data changed")
                    settings = read_target(conn, club_id, lifecycle=True)
                    if settings["sync_checkpoint"] != data["scope"]["sync_checkpoint"]:
                        raise GizmoError("Resource checkpoints were not committed")
                    cycles.append(
                        dict(parts=sorted(parts), api_calls=dict(api.calls), written=data["counts"], totals=after)
                    )
                report["cycles"] = cycles
                report["portrait"] = rebuild_club_portrait(conn, club_id)
                report["pulse"] = refresh_club(conn, club_id, gizmo_preview=True)
                if report["portrait"]["status"] != "updated" or report["pulse"]["status"] != "updated":
                    raise GizmoError("Projection verification did not complete")
            current = read_club(conn, 900001)
            if source_flags != {key: current[key] for key in source_flags}:
                raise GizmoError("Source service state changed; review required")
            check(read_club(conn, club_id))
            report.update(
                status="complete",
                source_flags_unchanged=True,
                test_service_disabled=True,
                test_sync_paused=True,
                limitation="Separate writes and projection functions verified; live clock slots covered by unit tests and timer configuration.",
            )
    except Exception as exc:
        report.update(status="error", error=type(exc).__name__)
        raise
    finally:
        conn.close()
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        atomic_json(DIRECTORY / "schedule-acceptance.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
