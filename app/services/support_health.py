from __future__ import annotations

import importlib
import os
import pkgutil
from pathlib import Path
from typing import Any

import migrations.versions
from app.config import (
    APP_ENV,
    APP_VERSION,
    CLUBMODULE_UPLOAD_ROOT,
    GIT_COMMIT,
    TECH_ALERT_BOT_TOKEN,
    TECH_ALERT_CHAT_ID,
)
from app.core import get_db_connection
from app.services.backup_monitor import get_backup_status


def get_expected_migration_revisions() -> list[str]:
    revisions = []
    for item in pkgutil.iter_modules(migrations.versions.__path__):
        if item.ispkg or item.name.startswith("_"):
            continue
        module = importlib.import_module(f"migrations.versions.{item.name}")
        revisions.append(getattr(module, "revision", item.name))
    return sorted(revisions)


def _fetch_applied_migrations(cursor) -> list[str]:
    try:
        cursor.execute("SELECT revision FROM schema_migrations ORDER BY revision")
        return [row["revision"] for row in cursor.fetchall()]
    except Exception:
        return []


def _fetch_count(cursor, table_name: str) -> int | None:
    try:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
        row = cursor.fetchone() or {}
        return int(row.get("cnt") or 0)
    except Exception:
        return None


def get_admin_system_health() -> dict[str, Any]:
    expected = get_expected_migration_revisions()
    conn = None
    database_ok = False
    applied: list[str] = []
    counts: dict[str, int | None] = {}
    error = None

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            row = cursor.fetchone() or {}
            database_ok = int(row.get("ok") or 0) == 1
            applied = _fetch_applied_migrations(cursor)
            counts = {
                "clubs": _fetch_count(cursor, "clubs"),
                "users": _fetch_count(cursor, "users"),
                "guests": _fetch_count(cursor, "guests"),
                "mailings": _fetch_count(cursor, "mailings"),
            }
    except Exception as exc:
        error = str(exc)
    finally:
        if conn:
            conn.close()

    pending = [revision for revision in expected if revision not in set(applied)]
    return {
        "ok": database_ok and not pending,
        "release": {
            "version": APP_VERSION,
            "commit": GIT_COMMIT or None,
        },
        "database": {
            "ok": database_ok,
            "error": error,
        },
        "migrations": {
            "expected": expected,
            "applied": applied,
            "pending": pending,
            "latest": expected[-1] if expected else None,
        },
        "counts": counts,
    }


def _status_item(key: str, title: str, status: str, message: str) -> dict[str, str]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "message": message,
    }


def _upload_storage_item() -> dict[str, str]:
    root = (CLUBMODULE_UPLOAD_ROOT or "").strip()
    if not root:
        return _status_item("upload_storage", "Файлы", "warning", "CLUBMODULE_UPLOAD_ROOT не задан")

    path = Path(root).expanduser()
    if not path.exists():
        return _status_item("upload_storage", "Файлы", "warning", f"Папка не найдена: {root}")
    if not path.is_dir():
        return _status_item("upload_storage", "Файлы", "error", f"Путь не является папкой: {root}")
    if not os.access(path, os.W_OK):
        return _status_item("upload_storage", "Файлы", "error", f"Нет прав на запись: {root}")
    return _status_item("upload_storage", "Файлы", "success", root)


def build_admin_readiness(
    *,
    system_health: dict[str, Any],
    alert_summary: dict[str, int],
    sync_summary: dict[str, int],
    recent_job_runs: list[dict[str, Any]],
    backup_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, str]] = []

    database = system_health.get("database") or {}
    if database.get("ok"):
        items.append(_status_item("database", "База данных", "success", "Соединение работает"))
    else:
        items.append(_status_item("database", "База данных", "error", database.get("error") or "Нет соединения"))

    pending = (system_health.get("migrations") or {}).get("pending") or []
    if pending:
        items.append(_status_item("migrations", "Миграции", "error", f"Ожидают применения: {len(pending)}"))
    else:
        latest = (system_health.get("migrations") or {}).get("latest") or "—"
        items.append(_status_item("migrations", "Миграции", "success", f"Последняя: {latest}"))

    error_alerts = int(alert_summary.get("error") or 0)
    warning_alerts = int(alert_summary.get("warning") or 0)
    if error_alerts:
        items.append(_status_item("operational_alerts", "Алерты", "error", f"Критические: {error_alerts}"))
    elif warning_alerts:
        items.append(_status_item("operational_alerts", "Алерты", "warning", f"Предупреждения: {warning_alerts}"))
    else:
        items.append(_status_item("operational_alerts", "Алерты", "success", "Активных предупреждений нет"))

    sync_errors = int(sync_summary.get("error") or 0)
    sync_stale = int(sync_summary.get("stale") or 0)
    if sync_errors:
        items.append(_status_item("sync_jobs", "Синхронизации", "error", f"Ошибки: {sync_errors}"))
    elif sync_stale:
        items.append(_status_item("sync_jobs", "Синхронизации", "warning", f"Устарело/нет данных: {sync_stale}"))
    else:
        items.append(_status_item("sync_jobs", "Синхронизации", "success", "Свежие данные по клубам"))

    problem_jobs = [
        job
        for job in recent_job_runs
        if (job.get("status") or "").lower() in {"error", "stale"}
    ]
    running_jobs = [
        job
        for job in recent_job_runs
        if (job.get("status") or "").lower() == "running"
    ]
    if problem_jobs:
        items.append(_status_item("background_jobs", "Фоновые задачи", "error", f"Проблемные запуски: {len(problem_jobs)}"))
    elif running_jobs:
        items.append(_status_item("background_jobs", "Фоновые задачи", "warning", f"Сейчас выполняется: {len(running_jobs)}"))
    else:
        items.append(_status_item("background_jobs", "Фоновые задачи", "success", "Последние запуски без ошибок"))

    if TECH_ALERT_BOT_TOKEN and TECH_ALERT_CHAT_ID:
        items.append(_status_item("tech_alerts", "Telegram-алерты", "success", "Настроены"))
    else:
        items.append(_status_item("tech_alerts", "Telegram-алерты", "warning", "Не заполнены TECH_ALERT_*"))

    items.append(_upload_storage_item())

    backup_status = backup_status or get_backup_status()
    backup_item_status = backup_status.get("status") or "warning"
    items.append(_status_item(
        "backups",
        "Backup",
        backup_item_status,
        backup_status.get("message") or "Статус backup неизвестен",
    ))

    if any(item["status"] == "error" for item in items):
        overall_status = "error"
        overall_label = "Требует внимания"
    elif any(item["status"] == "warning" for item in items):
        overall_status = "warning"
        overall_label = "Есть предупреждения"
    else:
        overall_status = "success"
        overall_label = "Готово"

    return {
        "overall_status": overall_status,
        "overall_label": overall_label,
        "environment": APP_ENV,
        "release": system_health.get("release") or {},
        "items": items,
    }
