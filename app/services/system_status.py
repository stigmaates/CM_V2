from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from app.core import get_db_connection
from app.services.job_runs import get_latest_job_runs_by_club
from app.services.mailing import ensure_auto_mailings

MSK_TZ = ZoneInfo("Europe/Moscow")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = PROJECT_ROOT / "logs"

UPDATE_TASKS = [
    {
        "key": "guests",
        "job_type": "sync_guests_incremental",
        "title": "Обновление гостей",
        "log_file": "sync_guests_incremental.log",
        "ok_after_minutes": 30,
    },
    {
        "key": "sessions",
        "job_type": "sync_sessions_incremental",
        "title": "Обновление сессий",
        "log_file": "sync_sessions_incremental.log",
        "ok_after_minutes": 10,
    },
    {
        "key": "operations",
        "job_type": "sync_operations_incremental",
        "title": "Обновление операций",
        "log_file": "sync_operations_incremental.log",
        "ok_after_minutes": 10,
    },
    {
        "key": "balance_topups",
        "job_type": "sync_balance_topups_incremental",
        "title": "Обновление пополнений",
        "log_file": "sync_balance_topups_incremental.log",
        "ok_after_minutes": 10,
    },
]

ERROR_MARKERS = ("traceback", "error", "exception", "failed", "importerror")


def _to_msk(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        return None
    if dt.tzinfo is None:
        # MySQL NOW() on the server is treated as UTC and displayed to owners as Moscow time.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK_TZ)


def _format_msk(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


def _file_mtime_msk(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(MSK_TZ)


def _log_has_recent_error(path: Path, max_bytes: int = 25000) -> bool:
    if not path.exists():
        return False
    try:
        data = path.read_bytes()[-max_bytes:].decode("utf-8", errors="ignore").lower()
    except Exception:
        return False
    return any(marker in data for marker in ERROR_MARKERS)


def _minutes_since(dt: datetime | None) -> float | None:
    if not dt:
        return None
    return (datetime.now(MSK_TZ) - dt).total_seconds() / 60


def _build_update_status(
    item: Dict[str, Any],
    latest_jobs_by_type: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    job_type = item.get("job_type")
    job_row = (latest_jobs_by_type or {}).get(job_type)
    if job_row:
        last_run = _to_msk(job_row.get("finished_at") or job_row.get("started_at"))
        minutes = _minutes_since(last_run)
        is_ok = (
            (job_row.get("status") or "").lower() == "success"
            and minutes is not None
            and minutes <= int(item["ok_after_minutes"])
        )
        return {
            "key": item["key"],
            "title": item["title"],
            "status": "работает" if is_ok else "не работает",
            "status_class": "ok" if is_ok else "bad",
            "last_run": _format_msk(last_run),
        }

    log_path = LOGS_DIR / item["log_file"]
    last_run = _file_mtime_msk(log_path)
    minutes = _minutes_since(last_run)
    has_error = _log_has_recent_error(log_path)
    is_ok = minutes is not None and minutes <= int(item["ok_after_minutes"]) and not has_error
    return {
        "key": item["key"],
        "title": item["title"],
        "status": "работает" if is_ok else "не работает",
        "status_class": "ok" if is_ok else "bad",
        "last_run": _format_msk(last_run),
    }


def _build_auto_status(row: Dict[str, Any]) -> Dict[str, Any]:
    is_enabled = bool(int(row.get("is_enabled") or 0))
    last_run = _to_msk(row.get("last_run_at"))
    minutes = _minutes_since(last_run)
    is_recent = minutes is not None and minutes <= 20

    if not is_enabled:
        status = "выключена"
        status_class = "off"
    elif is_recent:
        status = "работает"
        status_class = "ok"
    else:
        status = "не работает"
        status_class = "bad"

    return {
        "code": row.get("code"),
        "title": row.get("title") or row.get("code") or "Авторассылка",
        "status": status,
        "status_class": status_class,
        "last_run": _format_msk(last_run),
    }


def get_owner_settings_system_status(club_id: int) -> Dict[str, Any]:
    """Compact status block for owner settings. All displayed times are MSK."""
    job_types = [item["job_type"] for item in UPDATE_TASKS]
    try:
        latest_jobs_by_type = get_latest_job_runs_by_club(job_types).get(int(club_id), {})
    except Exception:
        latest_jobs_by_type = {}
    updates = [_build_update_status(item, latest_jobs_by_type) for item in UPDATE_TASKS]

    conn = get_db_connection()
    try:
        ensure_auto_mailings(conn, club_id)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT code, title, is_enabled, last_run_at
                FROM auto_mailing_settings
                WHERE club_id = %s
                ORDER BY id ASC
                """,
                (club_id,),
            )
            auto_rows = cur.fetchall() or []
    finally:
        conn.close()

    return {
        "timezone_label": "время МСК",
        "updates": updates,
        "auto_mailings": [_build_auto_status(row) for row in auto_rows],
    }
