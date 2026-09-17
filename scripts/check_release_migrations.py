"""Validate the migration set before building or deploying a release.

This check is intentionally database-free.  It protects the production
migration history while stage features are moved into a release branch in
small batches.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import migrations.versions  # noqa: E402


PRODUCTION_ANCHORS = {
    "0030_module_registration_capture",
    "0033_reusable_mission_templates",
    "0046_auto_mailing_send_windows",
}


def inspect_migrations() -> tuple[list[str], list[str]]:
    revisions: list[str] = []
    errors: list[str] = []

    for item in pkgutil.iter_modules(migrations.versions.__path__):
        if item.ispkg or item.name.startswith("_"):
            continue

        module = importlib.import_module(f"migrations.versions.{item.name}")
        revision = getattr(module, "revision", None)
        if not isinstance(revision, str) or not revision.strip():
            errors.append(f"{item.name}: missing non-empty revision")
            continue
        if revision != item.name:
            errors.append(f"{item.name}: revision is {revision!r}, expected the module name")
        if not callable(getattr(module, "upgrade", None)):
            errors.append(f"{item.name}: upgrade is not callable")
        revisions.append(revision)

    duplicates = sorted(revision for revision, count in Counter(revisions).items() if count > 1)
    for revision in duplicates:
        errors.append(f"duplicate revision: {revision}")

    missing_anchors = sorted(PRODUCTION_ANCHORS.difference(revisions))
    for revision in missing_anchors:
        errors.append(f"missing production migration anchor: {revision}")

    return sorted(revisions), errors


def main() -> int:
    revisions, errors = inspect_migrations()
    if errors:
        print("Release migration check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Release migration check passed: {len(revisions)} revisions.")
    print(f"First: {revisions[0]}")
    print(f"Last: {revisions[-1]}")
    print("Production anchors: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
