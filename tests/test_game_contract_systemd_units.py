from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_game_contracts_run_every_fifteen_minutes():
    service = (ROOT / "deploy/systemd/clubmodule-game-contracts.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/clubmodule-game-contracts.timer").read_text(encoding="utf-8")

    assert "WorkingDirectory=/root/cm_v2/CM_V2" in service
    assert "EnvironmentFile=/root/cm_v2/CM_V2/.env" in service
    assert "ExecStart=/root/cm_v2/CM_V2/venv/bin/python scripts/process_game_contracts.py" in service
    assert "/root/cm_stage/CM_V2" not in service
    assert "OnUnitActiveSec=15min" in timer
    assert "Unit=clubmodule-game-contracts.service" in timer
