"""Explicit stage pilot synchronization, with secrets outside the checkout/DB."""

import fcntl
import json
import logging
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.integrations.gizmo import GizmoClient, GizmoError
from app.integrations.gizmo_import import check_target, collect, save
from app.integrations.stage import require_stage_environment
from app.integrations.sync_jobs import GIZMO_SYNC_JOB
from app.services.guest_pulse import refresh_club
from app.services.job_runs import finish_job_run, start_job_run
from scripts.rebuild_user_portrait import rebuild_club_portrait

DIRECTORY = Path("/root/gizmo-stage-check")


def private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise GizmoError("Gizmo credentials must be an owner-only regular file (0600)")
        return json.load(stream)


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".gizmo-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def run_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GizmoError("Gizmo synchronization is already running") from None
        yield
    finally:
        os.close(fd)


def read_target(conn, club_id, *, allow_initial=False):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM clubs WHERE club_id=%s", (club_id,))
        check_target(cur.fetchone())
        cur.execute("SELECT settings FROM club_integrations WHERE club_id=%s", (club_id,))
        row = cur.fetchone()
    conn.rollback()
    settings = json.loads(row["settings"]) if row and isinstance(row["settings"], str) else (row or {}).get("settings")
    if allow_initial and row and not settings:
        return {}
    if not settings or not settings.get("source"):
        raise GizmoError("A successful verified pilot import is required before enabling sync")
    if settings.get("session_source") != "sessions+usersessions:same-id-user-span:v1":
        raise GizmoError("Session mapping has not been verified for this pilot")
    return settings


def sync_is_due(previous, now):
    # The file lock decides whether a "running" process is alive. Once acquired,
    # an interrupted run can resume immediately, without waiting for a timeout.
    if previous.get("status") in {"running", "queued"}:
        return True
    stamp = previous.get("finished_at_utc") or previous.get("last_success_at_utc")
    if not stamp:
        return True
    try:
        finished = datetime.fromisoformat(stamp)
        if finished.tzinfo is None:
            raise ValueError("Missing timezone")
    except (TypeError, ValueError):
        raise GizmoError("Invalid Gizmo synchronization timestamp") from None
    elapsed = (now - finished).total_seconds()
    # A backward clock correction must not suspend a club indefinitely.
    interval = 300 if previous.get("status") == "error" else 1800
    return elapsed < 0 or elapsed >= interval


def synchronize(conn, club_id, *, directory=DIRECTORY, only_if_due=False):
    require_stage_environment()
    with run_lock(directory / f"sync-{club_id}.lock"):
        credentials = private_json(directory / f"sync-{club_id}.json")
        if credentials.get("enabled") is not True:
            return {"club_id": club_id, "status": "paused"}
        end = datetime.now(UTC)
        status_path = directory / f"status-{club_id}.json"
        previous = private_json(status_path) if status_path.exists() else {}
        if only_if_due and not sync_is_due(previous, end):
            return {"club_id": club_id, "status": "not_due"}
        status = {
            "club_id": club_id,
            "status": "running",
            "phase": "collect",
            "started_at_utc": end.isoformat(),
            "last_success_at_utc": previous.get("last_success_at_utc"),
        }
        atomic_json(status_path, status)
        job_id = start_job_run(GIZMO_SYNC_JOB, club_id=club_id, metadata={"provider": "gizmo", "stage_preview": True})
        try:
            settings = read_target(conn, club_id, allow_initial=bool(credentials.get("connection")))
            source = settings.get("source") or credentials["connection"]
            certificate_pem = credentials.get("certificate_pem") or (directory / "server.pem").read_text()
            client = GizmoClient(
                port=source.get("port", 443),
                address=source["address"],
                server_name=source["server_name"],
                fingerprint=source["fingerprint"],
                certificate_pem=certificate_pem,
                api_key=credentials["api_key"],
            )
            if "certificate_pem" not in credentials:
                # Freeze the already approved legacy certificate per club. New
                # club credentials carry their own certificate from onboarding.
                credentials["certificate_pem"] = certificate_pem
                atomic_json(directory / f"sync-{club_id}.json", credentials)
            if not settings or credentials.get("requested_at_utc"):
                from app.integrations.gizmo_onboarding import inspect_connection

                status["phase"] = "connect"
                atomic_json(status_path, status)
                verified = inspect_connection(client)
                if settings and int(settings["branch_id"]) != verified["branch_id"]:
                    raise GizmoError("Cannot change the branch of an imported club")
                if not settings:
                    settings = verified
            status["phase"] = "collect"

            def progress(resource, count):
                status["progress"] = {"resource": resource, "records": count}
                atomic_json(status_path, status)

            data = collect(
                client,
                branch_id=int(settings["branch_id"]),
                start=None,
                end=end,
                cash_method_ids=set(settings["cash_method_ids"]),
                full_history=True,
                progress=progress,
            )
            data["scope"]["source"] = source
            rejected = data.get("rejected_sessions", [])
            status["session_time_examples"] = rejected[:10]
            atomic_json(
                directory / f"session-quality-{club_id}.json",
                {
                    "club_id": club_id,
                    "collected_at_utc": datetime.now(UTC).isoformat(),
                    "rejected_sessions": rejected,
                },
            )
            logging.getLogger(__name__).info("Gizmo: проверка пройдена, сохраняем данные в stage...")
            status["phase"] = "save"
            atomic_json(status_path, status)
            save(conn, club_id, data)
            status.update(
                counts=data["counts"],
                excluded_accounts=data.get("excluded_accounts", {}),
                nonpersonal_activity=data.get("nonpersonal_activity", {}),
                data_saved_at_utc=datetime.now(UTC).isoformat(),
                first_session_utc=min((r["date_start"].isoformat() for r in data.get("sessions", [])), default=None),
                first_topup_utc=min((r["topup_at"].isoformat() for r in data.get("topups", [])), default=None),
            )
            atomic_json(status_path, status)
            logging.getLogger(__name__).info("Gizmo: строим CRM-портреты клуба...")
            status["phase"] = "portraits"
            atomic_json(status_path, status)
            portrait = rebuild_club_portrait(conn, club_id)
            if portrait["status"] != "updated":
                raise GizmoError("Data saved but CRM portrait refresh did not complete; retry sync")
            status["portrait"] = portrait
            atomic_json(status_path, status)
            # Explicit preview continues to keep service, mail and rewards disabled.
            logging.getLogger(__name__).info("Gizmo: данные сохранены, пересчитываем Пульс...")
            status["phase"] = "pulse"
            atomic_json(status_path, status)
            pulse = refresh_club(conn, club_id, stage_gizmo_preview=True)
            if pulse["status"] != "updated":
                raise GizmoError("Data saved but Guest Pulse refresh did not complete; retry sync")
            status.update(
                status="complete", phase="complete", pulse=pulse, last_success_at_utc=datetime.now(UTC).isoformat()
            )
            status["finished_at_utc"] = status["last_success_at_utc"]
            atomic_json(status_path, status)
            if credentials.pop("requested_at_utc", None):
                atomic_json(directory / f"sync-{club_id}.json", credentials)
            finish_job_run(
                job_id,
                "success",
                rows_saved=sum(data["counts"].get(key, 0) for key in ("guests", "hosts", "sessions", "topups")),
                metadata={
                    "provider": "gizmo",
                    "stage_preview": True,
                    "counts": data["counts"],
                    "portrait": portrait,
                    "pulse": pulse,
                },
            )
            return status
        except Exception as exc:
            # No driver arguments, API key or guest data in status/logs.
            status.update(status="error", error=str(exc) if isinstance(exc, GizmoError) else type(exc).__name__)
            from app.integrations.gizmo_onboarding import public_error

            status["error_message"] = public_error(exc)
            status["finished_at_utc"] = datetime.now(UTC).isoformat()
            finish_job_run(
                job_id,
                "error",
                error_text=status["error"],
                metadata={
                    "provider": "gizmo",
                    "stage_preview": True,
                    "phase": status.get("phase", "collect"),
                    "data_saved_at_utc": status.get("data_saved_at_utc"),
                },
            )
            atomic_json(status_path, status)
            raise
