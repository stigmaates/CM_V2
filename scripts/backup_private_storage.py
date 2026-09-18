#!/usr/bin/env python3
"""Create a private archive of the admin drive and generated monthly reports."""

from __future__ import annotations

import os
import tarfile
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


def _validated_root(raw: str | None, variable: str) -> Path:
    if not raw:
        raise RuntimeError(f"Missing required environment variable: {variable}")
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.resolve() == Path("/"):
        raise RuntimeError(f"Unsafe private storage path in {variable}")
    if not path.is_dir():
        raise RuntimeError(f"Private storage directory does not exist: {path}")
    return path.resolve()


def main() -> int:
    if not ENV_FILE.is_file():
        raise RuntimeError(f"Environment file not found: {ENV_FILE}")

    values = dotenv_values(ENV_FILE)
    sources = {
        archive_name: _validated_root(values.get(variable), variable)
        for archive_name, variable in PRIVATE_ROOTS.items()
    }
    backup_dir = BACKUP_DIR.expanduser().resolve()
    for source in sources.values():
        if backup_dir == source or backup_dir.is_relative_to(source):
            raise RuntimeError("BACKUP_DIR must be outside private storage directories")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"private_storage_{timestamp}.tar.gz"
    temporary = backup_dir / f".{target.name}.tmp"

    try:
        with tarfile.open(temporary, "w:gz") as archive:
            archive.dereference = False
            for archive_name, source in sources.items():
                archive.add(source, arcname=archive_name, recursive=True)
        temporary.chmod(0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
