from datetime import datetime

from app.services import system_status


def test_update_status_uses_successful_background_job(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda dt: 1)

    item = {
        "key": "sessions",
        "job_type": "sync_sessions_incremental",
        "title": "Обновление сессий",
        "log_file": "sync_sessions_incremental.log",
        "ok_after_minutes": 10,
    }
    latest_jobs = {
        "sync_sessions_incremental": {
            "status": "success",
            "finished_at": datetime(2026, 7, 23, 21, 57, 3),
        }
    }

    status = system_status._build_update_status(item, latest_jobs)

    assert status["status"] == "работает"
    assert status["status_class"] == "ok"


def test_update_status_marks_failed_background_job_bad(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda dt: 1)

    item = {
        "key": "operations",
        "job_type": "sync_operations_incremental",
        "title": "Обновление операций",
        "log_file": "sync_operations_incremental.log",
        "ok_after_minutes": 10,
    }
    latest_jobs = {
        "sync_operations_incremental": {
            "status": "error",
            "finished_at": datetime(2026, 7, 23, 21, 57, 3),
        }
    }

    status = system_status._build_update_status(item, latest_jobs)

    assert status["status"] == "не работает"
    assert status["status_class"] == "bad"
