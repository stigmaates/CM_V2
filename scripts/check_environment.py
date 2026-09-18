from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import dotenv_values

REQUIRED_ALWAYS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "SECRET_KEY")
REQUIRED_PRODUCTION = ("BOT_TOKEN",)
RECOMMENDED = (
    "CM_BONUS_BOT_TOKEN",
    "CM_BONUS_ADMIN_CHAT_ID",
    "BOT_USERNAME",
    "TECH_ALERT_BOT_TOKEN",
    "TECH_ALERT_CHAT_ID",
)
RELEASE_REQUIRED = (
    "APP_VERSION",
    "GIT_COMMIT",
    "ADMIN_FILES_ROOT",
    "MONTHLY_REPORT_ROOT",
    "STEAM_API_KEY",
    "STEAM_PUBLIC_BASE_URL",
    "CS2_GC_BRIDGE_URL",
    "CS2_GC_BRIDGE_SECRET",
    "CS2_GC_REFRESH_TOKEN",
)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def validate_env(
    values: Mapping[str, str | None], *, release_features: bool = False
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    app_env = (values.get("APP_ENV") or "development").strip().lower()
    is_production = app_env == "production"

    for name in REQUIRED_ALWAYS:
        if not values.get(name):
            errors.append(f"Missing required variable: {name}")

    if is_production:
        for name in REQUIRED_PRODUCTION:
            if not values.get(name):
                errors.append(f"Missing required production variable: {name}")
    else:
        warnings.append("APP_ENV is not production")

    for name in RECOMMENDED:
        if not values.get(name):
            warnings.append(f"Recommended variable is empty: {name}")

    if (values.get("SECRET_KEY") or "") in {"change-me", "development-only-change-me"}:
        errors.append("SECRET_KEY uses an unsafe default value")

    upload_root = values.get("CLUBMODULE_UPLOAD_ROOT")
    if upload_root:
        path = Path(upload_root).expanduser()
        if not path.is_absolute():
            warnings.append("CLUBMODULE_UPLOAD_ROOT should be an absolute path")
    else:
        warnings.append("CLUBMODULE_UPLOAD_ROOT is empty; uploads will use code default")

    if release_features:
        if not is_production:
            errors.append("Release feature preflight requires APP_ENV=production")

        for name in RELEASE_REQUIRED:
            if not values.get(name):
                errors.append(f"Missing required release variable: {name}")

        public_origin = (values.get("STEAM_PUBLIC_BASE_URL") or "").strip()
        if public_origin:
            parsed = urlparse(public_origin)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append("STEAM_PUBLIC_BASE_URL must be an absolute HTTPS origin")

        bridge_url = (values.get("CS2_GC_BRIDGE_URL") or "").strip()
        if bridge_url:
            parsed = urlparse(bridge_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                errors.append("CS2_GC_BRIDGE_URL must use HTTP on localhost")

        bridge_secret = values.get("CS2_GC_BRIDGE_SECRET") or ""
        if bridge_secret and len(bridge_secret) < 32:
            errors.append("CS2_GC_BRIDGE_SECRET must contain at least 32 characters")

        public_path = Path(upload_root).expanduser() if upload_root else None
        private_paths: dict[str, Path] = {}
        for name in ("ADMIN_FILES_ROOT", "MONTHLY_REPORT_ROOT"):
            raw_path = values.get(name)
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            private_paths[name] = path
            if not path.is_absolute():
                errors.append(f"{name} must be an absolute path")
            if public_path and _path_is_within(path, public_path):
                errors.append(f"{name} must be outside CLUBMODULE_UPLOAD_ROOT")

        if len(set(private_paths.values())) != len(private_paths):
            errors.append("ADMIN_FILES_ROOT and MONTHLY_REPORT_ROOT must be different paths")

        for name in ("CLUBMODULE_UPLOAD_ROOT", "ADMIN_FILES_ROOT", "MONTHLY_REPORT_ROOT"):
            raw_path = (values.get(name) or "").lower()
            if "/stage" in raw_path or "cm_stage" in raw_path:
                errors.append(f"{name} contains a stage path")

        try:
            max_file_mb = int(values.get("ADMIN_FILES_MAX_MB") or "100")
            request_max_mb = int(values.get("ADMIN_FILES_REQUEST_MAX_MB") or "250")
            if max_file_mb <= 0 or request_max_mb <= 0:
                raise ValueError
            if request_max_mb < max_file_mb:
                errors.append("ADMIN_FILES_REQUEST_MAX_MB must be at least ADMIN_FILES_MAX_MB")
        except ValueError:
            errors.append("Admin file size limits must be positive integers")

    for command in ("mysql", "mysqldump"):
        if shutil.which(command) is None:
            warnings.append(f"Command not found in PATH: {command}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Cyber Bonus environment file.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument(
        "--release-features",
        action="store_true",
        help="Require configuration for every feature in the stage-to-production release",
    )
    args = parser.parse_args(argv)

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"Environment file not found: {env_path}", file=sys.stderr)
        return 2

    values = dotenv_values(env_path)
    errors, warnings = validate_env(values, release_features=args.release_features)

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        return 1

    print("Environment preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
