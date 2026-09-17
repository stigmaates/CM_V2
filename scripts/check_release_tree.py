"""Run repository-only safety checks for a production release candidate."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_release_migrations import inspect_migrations  # noqa: E402


FORBIDDEN_PRODUCTION_UNIT_TEXT = (
    "/root/cm_stage/CM_V2",
    "ALLOW_STAGE_GUEST_BOT",
    "ALLOW_STAGE_ADMIN_BOT",
    "DISABLE_OUTBOUND_MESSAGES",
    ".stage-no-outbound",
)


def inspect_production_units(root: Path = PROJECT_ROOT) -> list[str]:
    errors: list[str] = []
    unit_root = root / "deploy" / "systemd"
    if not unit_root.is_dir():
        return ["deploy/systemd directory is missing"]

    for path in sorted(unit_root.iterdir()):
        if not path.is_file() or path.name.startswith("clubmodule-stage-"):
            continue
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_PRODUCTION_UNIT_TEXT:
            if marker in text:
                errors.append(f"{path.relative_to(root)} contains stage-only marker {marker!r}")
    return errors


def main() -> int:
    revisions, migration_errors = inspect_migrations()
    errors = [*migration_errors, *inspect_production_units()]
    if errors:
        print("Release tree check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Release tree check passed: {len(revisions)} migrations and production units are safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
