import os
from pathlib import Path

import pytest

from app.integrations import gizmo_runtime as runtime


@pytest.fixture
def production(tmp_path, monkeypatch):
    directory = tmp_path / "production-state"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(runtime, "PRODUCTION_STATE", directory)
    return dict(
        root=Path("/root/cm_v2/CM_V2"),
        production=dict(APP_ENV="production", GIZMO_ENABLED="1", DB_HOST="db", DB_NAME="prod_db"),
        stage=dict(DB_NAME="stage_db"),
        loaded=("db", 3306, "prod_db"),
        enabled="1",
        directory=directory,
        uid=os.geteuid(),
    )


def test_production_requires_explicit_matching_identity_and_private_state(production):
    assert runtime.validate_production_target(**production) is None


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": "0"},
        {"enabled": ""},
        {"loaded": ("db", 3306, "stage_db")},
        {"root": Path("/root/cm_stage/CM_V2")},
        {"root": Path("/tmp/checkout")},
        {"loaded": ("other", 3306, "prod_db")},
        {"loaded": ("db", 3307, "prod_db")},
        {"stage": dict(DB_NAME="PROD_DB")},
        {"stage": {}},
        {"uid": -1},
        {"directory": Path("/root/gizmo-stage-check")},
    ],
)
def test_runtime_rejects_wrong_deployment_or_shared_state(production, change):
    with pytest.raises(ValueError):
        runtime.validate_production_target(**dict(production, **change))


@pytest.mark.parametrize(
    "field,value",
    [("GIZMO_ENABLED", "0"), ("GIZMO_ENABLED", None), ("APP_ENV", "stage"), ("DB_NAME", ""), ("DB_HOST", "")],
)
def test_environment_override_cannot_bypass_production_file_opt_in(production, field, value):
    production["production"][field] = value
    with pytest.raises(ValueError):
        runtime.validate_production_target(**production)


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_shared_directory_permissions_are_rejected(production, mode):
    production["directory"].chmod(mode)
    with pytest.raises(ValueError, match="private"):
        runtime.validate_production_target(**production)


def test_symlink_to_stage_state_is_rejected(production, tmp_path):
    path = production["directory"]
    path.rmdir()
    other = tmp_path / "stage"
    other.mkdir(mode=0o700)
    path.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="separate"):
        runtime.validate_production_target(**production)


def test_stage_keeps_original_guard_and_cannot_use_production_directory(monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", runtime.STAGE_ROOT)
    called = []
    monkeypatch.setattr(runtime, "require_stage_environment", lambda: called.append(True))
    runtime.require_gizmo_environment(directory=runtime.STAGE_STATE)
    assert called == [True]
    with pytest.raises(ValueError):
        runtime.require_gizmo_environment(directory=runtime.PRODUCTION_STATE)


def test_production_selects_separate_default_state(monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", runtime.PRODUCTION_ROOT)
    assert runtime.state_directory() == runtime.PRODUCTION_STATE
    monkeypatch.setattr(runtime, "ROOT", runtime.STAGE_ROOT)
    assert runtime.state_directory() == runtime.STAGE_STATE


def test_onboarding_pulse_cannot_bypass_runtime_guard(monkeypatch):
    from app.services.guest_pulse import refresh_club

    def reject():
        raise ValueError("Gizmo disabled")

    monkeypatch.setattr(runtime, "require_gizmo_environment", reject)
    with pytest.raises(ValueError, match="disabled"):
        refresh_club(None, 1, gizmo_preview=True)
