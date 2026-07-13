from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stage_backup_systemd_units_are_stage_scoped():
    service = (ROOT / "deploy/systemd/clubmodule-stage-backup.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/clubmodule-stage-backup.timer").read_text(encoding="utf-8")

    assert "WorkingDirectory=/root/cm_stage/CM_V2" in service
    assert "BACKUP_DIR=/root/cm_stage/CM_V2/backups" in service
    assert "ExecStart=/usr/bin/bash /root/cm_stage/CM_V2/scripts/backup_mysql.sh" in service
    assert "/root/cm_v2/CM_V2" not in service
    assert "OnCalendar=*-*-* 03:30:00" in timer
    assert "Persistent=true" in timer


def test_production_operational_alert_units_are_production_scoped():
    service = (ROOT / "deploy/systemd/clubmodule-operational-alerts.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/clubmodule-operational-alerts.timer").read_text(encoding="utf-8")

    assert "WorkingDirectory=/root/cm_v2/CM_V2" in service
    assert "EnvironmentFile=/root/cm_v2/CM_V2/.env" in service
    assert "ExecStart=/root/cm_v2/CM_V2/venv/bin/python scripts/send_operational_alerts.py" in service
    assert "/root/cm_stage/CM_V2" not in service
    assert "OnUnitActiveSec=5min" in timer
    assert "Unit=clubmodule-operational-alerts.service" in timer
