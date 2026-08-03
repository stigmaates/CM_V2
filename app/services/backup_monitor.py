from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import BACKUP_MAX_AGE_HOURS, BACKUP_MONITOR_DIRS

BACKUP_SUFFIXES = (".sql", ".sql.gz")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _backup_dirs(raw_value: str) -> list[Path]:
    dirs: list[Path] = []
    for chunk in (raw_value or "").split(","):
        item = chunk.strip()
        if not item:
            continue
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        dirs.append(path)
    return dirs


def _is_backup_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in BACKUP_SUFFIXES)


def _latest_backup(paths: list[Path]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for directory in paths:
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            candidates = [path for path in directory.rglob("*") if path.is_file() and _is_backup_file(path)]
        except Exception:
            continue
        for path in candidates:
            try:
                stat = path.stat()
            except Exception:
                continue
            current = {
                "path": str(path),
                "name": path.name,
                "size_bytes": int(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).replace(tzinfo=None),
            }
            if latest is None or current["mtime"] > latest["mtime"]:
                latest = current
    return latest


def get_backup_status(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    dirs = _backup_dirs(BACKUP_MONITOR_DIRS)
    latest = _latest_backup(dirs)
    configured_dirs = [str(path) for path in dirs]

    if not configured_dirs:
        return {
            "status": "warning",
            "message": "Папки backup не настроены",
            "configured_dirs": [],
            "latest": None,
            "age_hours": None,
            "max_age_hours": BACKUP_MAX_AGE_HOURS,
        }

    if not latest:
        return {
            "status": "error",
            "message": "Backup-файлы не найдены",
            "configured_dirs": configured_dirs,
            "latest": None,
            "age_hours": None,
            "max_age_hours": BACKUP_MAX_AGE_HOURS,
        }

    age_hours = max(0, int((now - latest["mtime"]).total_seconds() // 3600))
    if age_hours > int(BACKUP_MAX_AGE_HOURS):
        status = "error"
        message = f"Последний backup старше {BACKUP_MAX_AGE_HOURS} ч"
    else:
        status = "success"
        message = f"Последний backup: {age_hours} ч назад"

    return {
        "status": status,
        "message": message,
        "configured_dirs": configured_dirs,
        "latest": {
            **latest,
            "mtime": latest["mtime"].isoformat(sep=" "),
        },
        "age_hours": age_hours,
        "max_age_hours": BACKUP_MAX_AGE_HOURS,
    }
