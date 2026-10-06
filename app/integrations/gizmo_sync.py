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
from app.services.guest_pulse import refresh_club

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


def read_target(conn, club_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM clubs WHERE club_id=%s", (club_id,))
        check_target(cur.fetchone())
        cur.execute("SELECT settings FROM club_integrations WHERE club_id=%s", (club_id,))
        row = cur.fetchone()
    conn.rollback()
    settings = json.loads(row["settings"]) if row and isinstance(row["settings"], str) else (row or {}).get("settings")
    if not settings or not settings.get("source"):
        raise GizmoError("A successful verified pilot import is required before enabling sync")
    if settings.get("session_source") != "sessions+usersessions:same-id-user-span:v1":
        raise GizmoError("Session mapping has not been verified for this pilot")
    return settings


def synchronize(conn, club_id, *, directory=DIRECTORY):
    require_stage_environment()
    with run_lock(directory / f"sync-{club_id}.lock"):
        credentials = private_json(directory / f"sync-{club_id}.json")
        if credentials.get("enabled") is not True:
            return {"club_id": club_id, "status": "paused"}
        settings = read_target(conn, club_id)
        source = settings["source"]
        client = GizmoClient(
            address=source["address"],
            server_name=source["server_name"],
            fingerprint=source["fingerprint"],
            certificate_pem=(directory / "server.pem").read_text(),
            api_key=credentials["api_key"],
        )
        end = datetime.now(UTC)
        status_path = directory / f"status-{club_id}.json"
        previous = private_json(status_path) if status_path.exists() else {}
        status = {
            "club_id": club_id,
            "status": "running",
            "started_at_utc": end.isoformat(),
            "last_success_at_utc": previous.get("last_success_at_utc"),
        }
        atomic_json(status_path, status)
        try:
            data = collect(
                client,
                branch_id=int(settings["branch_id"]),
                start=None,
                end=end,
                cash_method_ids=set(settings["cash_method_ids"]),
                full_history=True,
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
            save(conn, club_id, data)
            status.update(
                counts=data["counts"],
                data_saved_at_utc=datetime.now(UTC).isoformat(),
                first_session_utc=min((r["date_start"].isoformat() for r in data.get("sessions", [])), default=None),
                first_topup_utc=min((r["topup_at"].isoformat() for r in data.get("topups", [])), default=None),
            )
            atomic_json(status_path, status)
            # Explicit preview continues to keep service, mail and rewards disabled.
            logging.getLogger(__name__).info("Gizmo: данные сохранены, пересчитываем Пульс...")
            pulse = refresh_club(conn, club_id, stage_gizmo_preview=True)
            if pulse["status"] != "updated":
                raise GizmoError("Data saved but Guest Pulse refresh did not complete; retry sync")
            status.update(status="complete", pulse=pulse, last_success_at_utc=datetime.now(UTC).isoformat())
            atomic_json(status_path, status)
            return status
        except Exception as exc:
            # No driver arguments, API key or guest data in status/logs.
            status.update(status="error", error=str(exc) if isinstance(exc, GizmoError) else type(exc).__name__)
            atomic_json(status_path, status)
            raise
