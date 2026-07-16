from datetime import UTC, datetime
import os

from app.services import backup_monitor


def test_backup_status_reports_latest_fresh_backup(monkeypatch, tmp_path):
    backup_file = tmp_path / "cm_stage_20260701.sql.gz"
    backup_file.write_text("backup", encoding="utf-8")
    mtime = datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC).timestamp()
    os.utime(backup_file, (mtime, mtime))

    monkeypatch.setattr(backup_monitor, "BACKUP_MONITOR_DIRS", str(tmp_path))
    monkeypatch.setattr(backup_monitor, "BACKUP_MAX_AGE_HOURS", 24)

    status = backup_monitor.get_backup_status(now=datetime(2026, 7, 1, 12, 0, 0))

    assert status["status"] == "success"
    assert status["age_hours"] == 2
    assert status["latest"]["name"] == "cm_stage_20260701.sql.gz"


def test_backup_status_reports_missing_backup(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_monitor, "BACKUP_MONITOR_DIRS", str(tmp_path))
    monkeypatch.setattr(backup_monitor, "BACKUP_MAX_AGE_HOURS", 24)

    status = backup_monitor.get_backup_status(now=datetime(2026, 7, 1, 12, 0, 0))

    assert status["status"] == "error"
    assert status["latest"] is None


def test_backup_status_reports_stale_backup(monkeypatch, tmp_path):
    backup_file = tmp_path / "cm_stage_old.sql"
    backup_file.write_text("backup", encoding="utf-8")
    mtime = datetime(2026, 6, 29, 10, 0, 0, tzinfo=UTC).timestamp()
    os.utime(backup_file, (mtime, mtime))

    monkeypatch.setattr(backup_monitor, "BACKUP_MONITOR_DIRS", str(tmp_path))
    monkeypatch.setattr(backup_monitor, "BACKUP_MAX_AGE_HOURS", 24)

    status = backup_monitor.get_backup_status(now=datetime(2026, 7, 1, 12, 0, 0))

    assert status["status"] == "error"
    assert status["age_hours"] == 50
