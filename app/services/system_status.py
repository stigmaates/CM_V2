from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.core import get_db_connection
from app.services.mailing import ensure_auto_mailings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"

SCRIPT_STATUS_CONFIG = [
    {
        "key": "process_mailings",
        "title": "Ручные рассылки",
        "log_file": "process_mailings.log",
        "expected_minutes": 5,
        "description": "Отправка созданных рассылок",
    },
    {
        "key": "process_auto_mailings",
        "title": "Авторассылки",
        "log_file": "process_auto_mailings.log",
        "expected_minutes": 15,
        "description": "Первый визит, стрики, реактивация",
    },
    {
        "key": "sync_guests",
        "title": "Обновление гостей",
        "log_file": "sync_guests_incremental.log",
        "expected_minutes": 30,
        "description": "Синхронизация базы гостей",
    },
    {
        "key": "sync_sessions",
        "title": "Обновление сессий",
        "log_file": "sync_sessions_incremental.log",
        "expected_minutes": 10,
        "description": "Синхронизация игровых сессий",
    },
    {
        "key": "sync_operations",
        "title": "Обновление операций",
        "log_file": "sync_operations_incremental.log",
        "expected_minutes": 10,
        "description": "Синхронизация платежей/операций",
    },
    {
        "key": "rebuild_user_portrait",
        "title": "Пересборка портретов",
        "log_file": "rebuild_user_portrait.log",
        "expected_minutes": 30,
        "description": "CRM-метрики и сегменты гостей",
    },
]

ERROR_MARKERS = ("traceback", "error", "exception", "failed", "importerror", "critical", "timeout")


def _format_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


def _read_tail(path: Path, max_lines: int = 80) -> List[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]
    except Exception:
        return []


def _last_meaningful_line(lines: List[str]) -> str:
    for line in reversed(lines):
        line = line.strip()
        if line:
            return line[:220]
    return "Лог пустой"


def _script_status(item: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    path = LOG_DIR / item["log_file"]
    lines = _read_tail(path)
    last_line = _last_meaningful_line(lines)
    has_errors = any(any(marker in line.lower() for marker in ERROR_MARKERS) for line in lines[-30:])

    last_dt = None
    minutes_ago = None
    if path.exists():
        try:
            last_dt = datetime.fromtimestamp(path.stat().st_mtime)
            minutes_ago = int((now - last_dt).total_seconds() // 60)
        except Exception:
            pass

    expected = int(item.get("expected_minutes") or 15)
    if last_dt is None:
        status = "error"
        status_text = "нет лога"
    elif has_errors:
        status = "error"
        status_text = "есть ошибка"
    elif minutes_ago is not None and minutes_ago > expected:
        status = "warning"
        status_text = "давно не запускался"
    else:
        status = "ok"
        status_text = "работает"

    return {
        **item,
        "status": status,
        "status_text": status_text,
        "last_update": _format_dt(last_dt),
        "minutes_ago": minutes_ago,
        "last_line": last_line,
    }


def _auto_mailing_statuses(club_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        ensure_auto_mailings(conn, club_id)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ams.code,
                    ams.title,
                    ams.description,
                    ams.is_enabled,
                    ams.last_run_at,
                    ams.last_mailing_id,
                    ams.updated_at,
                    (
                        SELECT COUNT(*)
                        FROM auto_mailing_logs aml
                        WHERE aml.club_id = ams.club_id
                          AND aml.automation_code = ams.code
                          AND aml.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    ) AS sent_7d
                FROM auto_mailing_settings ams
                WHERE ams.club_id = %s
                ORDER BY ams.id ASC
                """,
                (club_id,),
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    result = []
    for row in rows:
        enabled = bool(int(row.get("is_enabled") or 0))
        result.append({
            "code": row.get("code"),
            "title": row.get("title") or row.get("code"),
            "description": row.get("description") or "",
            "status": "ok" if enabled else "muted",
            "status_text": "включена" if enabled else "выключена",
            "last_run": _format_dt(row.get("last_run_at")),
            "last_mailing_id": row.get("last_mailing_id"),
            "sent_7d": int(row.get("sent_7d") or 0),
        })
    return result


def get_settings_system_status(club_id: int) -> Dict[str, Any]:
    now = datetime.now()
    scripts = [_script_status(item, now) for item in SCRIPT_STATUS_CONFIG]
    automailings = _auto_mailing_statuses(int(club_id))

    errors = sum(1 for item in scripts if item["status"] == "error")
    warnings = sum(1 for item in scripts if item["status"] == "warning")
    if errors:
        overall_status = "error"
        overall_text = "есть ошибки"
    elif warnings:
        overall_status = "warning"
        overall_text = "нужно проверить"
    else:
        overall_status = "ok"
        overall_text = "всё работает"

    last_script_dt = None
    for item in scripts:
        path = LOG_DIR / item["log_file"]
        if path.exists():
            try:
                dt = datetime.fromtimestamp(path.stat().st_mtime)
                if last_script_dt is None or dt > last_script_dt:
                    last_script_dt = dt
            except Exception:
                pass

    return {
        "overall_status": overall_status,
        "overall_text": overall_text,
        "last_update": _format_dt(last_script_dt),
        "scripts": scripts,
        "automailings": automailings,
    }
