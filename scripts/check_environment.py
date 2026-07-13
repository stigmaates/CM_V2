from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Mapping

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


def validate_env(values: Mapping[str, str | None]) -> tuple[list[str], list[str]]:
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

    for command in ("mysql", "mysqldump"):
        if shutil.which(command) is None:
            warnings.append(f"Command not found in PATH: {command}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Cyber Bonus environment file.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    args = parser.parse_args(argv)

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"Environment file not found: {env_path}", file=sys.stderr)
        return 2

    values = dotenv_values(env_path)
    errors, warnings = validate_env(values)

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
