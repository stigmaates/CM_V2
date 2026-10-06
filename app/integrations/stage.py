"""Identify the actual isolated stage, independently of Flask's runtime mode."""
from pathlib import Path

STAGE_ROOT = Path('/root/cm_stage/CM_V2')
PRODUCTION_ENV = Path('/root/cm_v2/CM_V2/.env')
ROOT = Path(__file__).resolve().parents[2]


def validate_stage_target(*, root, stage, production, loaded, outbound_blocked):
    if root.resolve() != STAGE_ROOT:
        raise ValueError('Gizmo pilot must run from /root/cm_stage/CM_V2')
    if not outbound_blocked:
        raise ValueError('Stage outbound stop marker is required')
    stage_name, production_name = stage.get('DB_NAME'), production.get('DB_NAME')
    if not stage_name or not production_name or stage_name.casefold() == production_name.casefold():
        raise ValueError('Stage and production must have distinct database names')
    if not stage.get('DB_HOST') or not production.get('DB_HOST'):
        raise ValueError('Missing stage/production database configuration')
    expected = (stage['DB_HOST'], int(stage.get('DB_PORT') or 3306), stage_name)
    if loaded != expected:
        raise ValueError('Loaded database settings do not match the stage environment file')


def require_stage_environment():
    from dotenv import dotenv_values

    from app.config import DB_HOST, DB_NAME, DB_PORT

    validate_stage_target(
        root=ROOT,
        stage=dotenv_values(ROOT / '.env'),
        production=dotenv_values(PRODUCTION_ENV),
        loaded=(DB_HOST, DB_PORT, DB_NAME),
        outbound_blocked=(ROOT / '.stage-no-outbound').is_file(),
    )


def stage_pilot_available():
    try:
        require_stage_environment()
    except (OSError, ValueError):
        return False
    return True
