"""Explicit Gizmo runtime identity and separate private state for each deployment.

Stage retains its strict database/outbound isolation. Production additionally
requires opt-in in its own .env; merely deploying the code enables nothing.
Acceptance scripts continue to use require_stage_environment directly.
"""

import os
import stat
from pathlib import Path

from dotenv import dotenv_values

from app.integrations.stage import ROOT, STAGE_ROOT, require_stage_environment

PRODUCTION_ROOT = Path("/root/cm_v2/CM_V2")
STAGE_STATE = Path("/root/gizmo-stage-check")
PRODUCTION_STATE = Path("/var/lib/cyber-bonus/gizmo")


def is_stage_runtime():
    return ROOT.resolve() == STAGE_ROOT


def state_directory():
    return PRODUCTION_STATE if ROOT.resolve() == PRODUCTION_ROOT else STAGE_STATE


def validate_production_target(*, root, production, stage, loaded, enabled, directory, uid):
    if root.resolve() != PRODUCTION_ROOT:
        raise ValueError("Gizmo production checkout is not recognized")
    if enabled != "1" or str(production.get("GIZMO_ENABLED") or "").strip() != "1":
        raise ValueError("Gizmo is not enabled in the production environment")
    if str(production.get("APP_ENV") or "").strip().lower() != "production":
        raise ValueError("Production APP_ENV must be production")
    name = production.get("DB_NAME")
    if not name or not production.get("DB_HOST") or not stage.get("DB_NAME"):
        raise ValueError("Database identities must be configured")
    if name.casefold() == stage["DB_NAME"].casefold():
        raise ValueError("Production and stage databases must be separate")
    expected = (production["DB_HOST"], int(production.get("DB_PORT") or 3306), name)
    if loaded != expected:
        raise ValueError("Loaded database does not match production .env")
    if directory != PRODUCTION_STATE or directory.resolve() != PRODUCTION_STATE:
        raise ValueError("Production Gizmo state must use its separate directory")
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Gizmo state must be a private directory owned by the service user (0700)")


def require_gizmo_environment(*, directory=None):
    directory = Path(directory) if directory is not None else state_directory()
    if is_stage_runtime():
        require_stage_environment()
        if directory.resolve() != STAGE_STATE:
            raise ValueError("Stage Gizmo state must stay separate from production")
        return
    if ROOT.resolve() != PRODUCTION_ROOT:
        raise ValueError("Gizmo deployment is not recognized")
    from app.config import DB_HOST, DB_NAME, DB_PORT

    validate_production_target(
        root=ROOT,
        production=dotenv_values(PRODUCTION_ROOT / ".env"),
        stage=dotenv_values(STAGE_ROOT / ".env"),
        loaded=(DB_HOST, DB_PORT, DB_NAME),
        enabled=os.getenv("GIZMO_ENABLED", "").strip(),
        directory=directory,
        uid=os.geteuid(),
    )


def gizmo_available():
    try:
        require_gizmo_environment()
    except (OSError, ValueError):
        return False
    return True
