#!/usr/bin/env python3
"""Validate that the CS2 bridge can be installed reproducibly for production.

This check is intentionally repository-only: it does not start Steam, access a
refresh token, or contact the network. Run it before `npm ci --omit=dev` on the
production candidate host.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = ROOT / "services" / "cs2_gc"
PACKAGE_FILE = BRIDGE_DIR / "package.json"
LOCK_FILE = BRIDGE_DIR / "package-lock.json"


def fail(message: str) -> int:
    print(f"CS2 bridge release check failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if not PACKAGE_FILE.is_file():
        return fail("services/cs2_gc/package.json is missing")
    if not LOCK_FILE.is_file():
        return fail(
            "services/cs2_gc/package-lock.json is missing; generate and review it with Node 18+ before release"
        )

    try:
        package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"invalid JSON: {exc}")

    dependencies = package.get("dependencies")
    lock_root = (lock.get("packages") or {}).get("") or {}
    lock_dependencies = lock_root.get("dependencies")
    if not isinstance(dependencies, dict) or not dependencies:
        return fail("package.json must declare bridge dependencies")
    if not isinstance(lock_dependencies, dict):
        return fail("package-lock.json must include root package dependencies")

    mismatches = [
        name
        for name, version in sorted(dependencies.items())
        if lock_dependencies.get(name) != version
    ]
    if mismatches:
        return fail("lock root dependencies differ from package.json: " + ", ".join(mismatches))

    engine = str((package.get("engines") or {}).get("node") or "")
    if ">=18" not in engine:
        return fail("package.json must require Node.js 18 or newer")

    print(
        "CS2 bridge release check passed: "
        f"{len(dependencies)} direct dependencies are locked and Node requirement is {engine}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
