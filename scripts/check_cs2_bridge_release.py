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
DISABLED_ZIP_PACKAGE = BRIDGE_DIR / "vendor" / "adm-zip-disabled" / "package.json"


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

    overrides = package.get("overrides") or {}
    if (overrides.get("steam-user") or {}).get("adm-zip") != "$adm-zip":
        return fail("steam-user must use the fail-closed adm-zip replacement")
    if (overrides.get("steam-appticket@1.0.2") or {}).get("protobufjs") != "7.6.6":
        return fail("steam-appticket protobufjs override must remain pinned to 7.6.6")
    if dependencies.get("adm-zip") != "file:vendor/adm-zip-disabled":
        return fail("adm-zip must resolve to vendor/adm-zip-disabled")
    if not DISABLED_ZIP_PACKAGE.is_file():
        return fail("fail-closed adm-zip replacement is missing")

    lock_packages = lock.get("packages") or {}
    adm_zip_lock = lock_packages.get("node_modules/adm-zip") or {}
    if adm_zip_lock.get("resolved") != "vendor/adm-zip-disabled":
        return fail("lock file does not resolve adm-zip to the local replacement")
    protobuf_lock = lock_packages.get("node_modules/protobufjs") or {}
    if protobuf_lock.get("version") != "7.6.6":
        return fail("lock file must pin protobufjs 7.6.6")

    engine = str((package.get("engines") or {}).get("node") or "")
    if ">=18" not in engine:
        return fail("package.json must require Node.js 18 or newer")

    print(
        "CS2 bridge release check passed: "
        f"{len(dependencies)} direct dependencies are locked, security overrides are pinned, "
        f"and Node requirement is {engine}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
