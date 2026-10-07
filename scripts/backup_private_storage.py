#!/usr/bin/env python3
"""Create a private archive of the admin drive and generated monthly reports."""

from __future__ import annotations

import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", ROOT / "backups"))
PRIVATE_ROOTS = {
    "admin-drive": "ADMIN_FILES_ROOT",
    "monthly-reports": "MONTHLY_REPORT_ROOT",
}
GIZMO_PRODUCTION_STATE = Path("/var/lib/cyber-bonus/gizmo")


def _validated_root(raw: str | None, variable: str) -> Path:
    if not raw:
        raise RuntimeError(f"Missing required environment variable: {variable}")
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.resolve() == Path("/"):
        raise RuntimeError(f"Unsafe private storage path in {variable}")
    if not path.is_dir():
        raise RuntimeError(f"Private storage directory does not exist: {path}")
    return path.resolve()


def backup_sources(values: dict) -> dict[str, Path]:
    sources = {
        archive_name: _validated_root(values.get(variable), variable)
        for archive_name, variable in PRIVATE_ROOTS.items()
    }
    if str(values.get("GIZMO_ENABLED") or "").strip() == "1":
        if str(values.get("APP_ENV") or "").strip().lower() != "production":
            raise RuntimeError("Gizmo production backup requires APP_ENV=production")
        if GIZMO_PRODUCTION_STATE.resolve() != GIZMO_PRODUCTION_STATE:
            raise RuntimeError("Gizmo backup source must not be redirected by a symlink")
        sources["gizmo"] = _validated_root(str(GIZMO_PRODUCTION_STATE), "Gizmo private state")
    return sources


def main() -> int:
    if not ENV_FILE.is_file():
        raise RuntimeError(f"Environment file not found: {ENV_FILE}")

    values = dotenv_values(ENV_FILE)
    sources = backup_sources(values)
    backup_dir = BACKUP_DIR.expanduser().resolve()
    for source in sources.values():
        if backup_dir == source or backup_dir.is_relative_to(source):
            raise RuntimeError("BACKUP_DIR must be outside private storage directories")

    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"private_storage_{timestamp}.tar.gz"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=backup_dir)
    temporary = Path(temporary_name)

    try:
        # Keep secrets private while writing, not just after closing the archive.
        with os.fdopen(descriptor, "wb") as output:
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                archive.dereference = False
                for archive_name, source in sources.items():
                    archive.add(source, arcname=archive_name, recursive=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
