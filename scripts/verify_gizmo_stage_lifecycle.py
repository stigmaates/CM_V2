"""Verify real stage onboarding/lifecycle on a separate, disposable Gizmo club.

Reuses the source club's private API key without printing it. The source club
is read-only. The acceptance club is always disabled and paused on exit.
"""

import argparse
import json
import logging
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import session

from app.core import get_db_connection
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_lifecycle import read_club, set_service
from app.integrations.gizmo_onboarding import pause_sync, queue_setup
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, read_target, run_lock, synchronize
from app.integrations.stage import require_stage_environment
from app.main import app
from app.routes.admin.clubs import create_club

TEST_NAME = "Gizmo — проверка подключения на стейдже"


def totals(conn, club_id):
    conn.rollback()
    result = {}
    with conn.cursor() as cur:
        for table in ("guests", "club_pc_names", "guest_sessions", "guest_balance_topups"):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE club_id=%s", (club_id,))
            result[table] = int(cur.fetchone()["n"])
        cur.execute("SELECT COALESCE(SUM(amount),0) AS amount FROM guest_balance_topups WHERE club_id=%s", (club_id,))
        result["topups_amount"] = str(cur.fetchone()["amount"])
    conn.rollback()
    return result


def run(source_club_id, *, directory=DIRECTORY):
    require_stage_environment()
    conn = get_db_connection()
    manifest = directory / f"acceptance-{source_club_id}.json"
    report = dict(started_at_utc=datetime.now(UTC).isoformat(), source_club_id=source_club_id, status="running")
    club_id = None
    try:
        with run_lock(directory / "acceptance.lock"):
            source = read_club(conn, source_club_id)
            if not source or source.get("integration_provider") != "gizmo":
                raise GizmoError("Source must be an existing Gizmo club")
            source_flags = {k: source[k] for k in ("service_enabled", "integration_ready")}
            source_credentials = private_json(directory / f"sync-{source_club_id}.json")
            settings = read_target(conn, source_club_id, lifecycle=True)
            if manifest.exists():
                candidate = private_json(manifest)
                test_id = int(candidate["test_club_id"])
                test_club = read_club(conn, test_id)
                if (
                    test_id == source_club_id
                    or not test_club
                    or test_club.get("name") != TEST_NAME
                    or test_club.get("owner_id") is not None
                ):
                    raise GizmoError("Acceptance club identity differs; no existing club was changed")
                club_id = test_id
            else:
                # Exercise the real admin creation route with the same fields
                # as the browser form. Never puts credentials in shell/history.
                with app.test_request_context(
                    "/admin/clubs/create",
                    method="POST",
                    data=dict(
                        name=TEST_NAME,
                        integration_provider="gizmo",
                        timezone=source.get("timezone"),
                        gizmo_api_key=source_credentials["api_key"],
                        **settings["source"],
                    ),
                ):
                    session.update(user_id=0, role="admin")
                    response = create_club()
                if not hasattr(response, "status_code") or response.status_code != 302:
                    raise GizmoError("Test club creation did not succeed")
                club_id = int(response.location.rstrip("/").split("/")[-2])
                atomic_json(manifest, dict(test_club_id=club_id, source_club_id=source_club_id))
            report["test_club_id"] = club_id
            print(f"Тестовый клуб: {club_id}. Исходный клуб {source_club_id} не изменяется.", flush=True)
            test_club = read_club(conn, club_id)
            if test_club.get("service_enabled"):
                set_service(conn, club_id, False, directory=directory)
            credentials = private_json(directory / f"sync-{club_id}.json")
            queue_setup(
                conn,
                club_id,
                dict(credentials["connection"], api_key=source_credentials["api_key"]),
                directory=directory,
            )
            print("Первичная загрузка через настройки формы…", flush=True)
            first = synchronize(conn, club_id, directory=directory)
            if first["status"] != "complete":
                raise GizmoError("Initial import did not complete")
            credentials = private_json(directory / f"sync-{club_id}.json")
            if credentials["connection"]["fingerprint"] != settings["source"]["fingerprint"]:
                raise GizmoError("Source and test certificate fingerprints differ")
            report["initial"] = totals(conn, club_id)
            report["initial_counts"] = first["counts"]
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM guests WHERE club_id=%s AND telegram_id IS NOT NULL", (club_id,))
                if int(cur.fetchone()["n"]):
                    raise GizmoError("Acceptance club has Telegram links; service was not enabled")
            conn.rollback()
            print("Проверяем включение и рабочий цикл…", flush=True)
            set_service(conn, club_id, True, directory=directory)
            active = synchronize(conn, club_id, directory=directory, only_if_due=True)
            if active["status"] != "complete":
                raise GizmoError("Active cycle did not complete")
            report["active"] = totals(conn, club_id)
            report["active_pulse"] = active["pulse"]
            set_service(conn, club_id, False, directory=directory)
            if synchronize(conn, club_id, directory=directory)["status"] != "paused":
                raise GizmoError("Disabled club was not paused")
            report["disabled_stops_sync"] = True
            print("Проверяем обновление выключенного клуба и повторное включение…", flush=True)
            credentials = private_json(directory / f"sync-{club_id}.json")
            queue_setup(conn, club_id, credentials["connection"], directory=directory)
            if synchronize(conn, club_id, directory=directory)["status"] != "complete":
                raise GizmoError("Explicit refresh did not complete")
            if synchronize(conn, club_id, directory=directory)["status"] != "paused":
                raise GizmoError("Disabled refresh repeated without request")
            set_service(conn, club_id, True, directory=directory)
            report["resume_enabled"] = bool(read_club(conn, club_id)["service_enabled"])
            current_source = read_club(conn, source_club_id)
            if source_flags != {k: current_source[k] for k in source_flags}:
                raise GizmoError("Source service flags changed concurrently; review required")
            report["source_flags_unchanged"] = True
            report["status"] = "complete"
    except BaseException as exc:
        report["status"] = "error"
        report["error"] = str(exc) if isinstance(exc, GizmoError) else type(exc).__name__
        raise
    finally:
        try:
            if club_id is not None:
                club = read_club(conn, club_id)
                if club.get("service_enabled"):
                    set_service(conn, club_id, False, directory=directory)
                pause_sync(conn, club_id, directory=directory)
                report["test_service_disabled"] = True
                report["test_sync_paused"] = True
        except BaseException as exc:
            report["status"] = "error"
            report["cleanup_error"] = type(exc).__name__
            raise
        finally:
            report["finished_at_utc"] = datetime.now(UTC).isoformat()
            atomic_json(directory / f"acceptance-report-{source_club_id}.json", report)
            conn.close()
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-club-id", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    def stop_requested(signum, frame):
        raise KeyboardInterrupt("Acceptance stopped")

    signal.signal(signal.SIGTERM, stop_requested)
    try:
        run(args.source_club_id)
    except Exception as exc:
        print(str(exc) if isinstance(exc, GizmoError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
