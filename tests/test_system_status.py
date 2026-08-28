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


def test_update_status_displays_time_in_club_timezone(monkeypatch):
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
            "status": "success",
            "finished_at": datetime(2026, 8, 28, 7, 13),
        }
    }

    status = system_status._build_update_status(
        item,
        latest_jobs,
        timezone_name="Asia/Yekaterinburg",
    )

    assert status["last_run"] == "28.08.2026 12:13"


def test_auto_status_shows_night_pause_in_club_timezone(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda dt: 120)

    status = system_status._build_auto_status(
        {
            "code": "inactive_14_bonus",
            "title": "Вернуть гостей после неактива",
            "is_enabled": 1,
            "last_run_at": datetime(2026, 8, 27, 19, 25),
        },
        timezone_name="Asia/Yekaterinburg",
        now=datetime(2026, 8, 28, 0, 30),
    )

    assert status["status"] == "ночная пауза до 10:00"
    assert status["status_class"] == "off"
    assert status["last_run"] == "28.08.2026 00:25"


def test_auto_status_marks_stale_job_bad_during_send_window(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda dt: 30)

    status = system_status._build_auto_status(
        {
            "code": "first_visit_survey",
            "title": "Опрос после первого визита",
            "is_enabled": 1,
            "last_run_at": datetime(2026, 8, 28, 6, 30),
        },
        timezone_name="Asia/Yekaterinburg",
        now=datetime(2026, 8, 28, 12, 0),
    )

    assert status["status"] == "не работает"
    assert status["status_class"] == "bad"


def test_disabled_auto_mailing_stays_disabled_at_night(monkeypatch):
    monkeypatch.setattr(system_status, "_minutes_since", lambda dt: None)

    status = system_status._build_auto_status(
        {
            "code": "streak_expiring_reminder",
            "title": "Напоминание о стрике",
            "is_enabled": 0,
            "last_run_at": None,
        },
        timezone_name="Asia/Yekaterinburg",
        now=datetime(2026, 8, 28, 2, 0),
    )

    assert status["status"] == "выключена"
    assert status["status_class"] == "off"
