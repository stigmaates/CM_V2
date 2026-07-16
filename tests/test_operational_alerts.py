from datetime import datetime, timedelta

from app.services import operational_alerts


def test_build_operational_alerts_reports_missing_syncs():
    alerts = operational_alerts.build_operational_alerts(
        clubs=[{"club_id": 7, "name": "Test Club"}],
        latest_jobs_by_club={},
        problem_jobs=[],
        stuck_mailings=[],
        now=datetime(2026, 6, 30, 12, 0, 0),
    )

    assert len(alerts) == 3
    assert {alert["code"] for alert in alerts} == {"sync_missing"}
    assert all(alert["severity"] == "warning" for alert in alerts)


def test_build_operational_alerts_reports_stale_sync():
    now = datetime(2026, 6, 30, 12, 0, 0)
    alerts = operational_alerts.build_operational_alerts(
        clubs=[{"club_id": 7, "name": "Test Club"}],
        latest_jobs_by_club={
            7: {
                "sync_guests_incremental": {
                    "status": "success",
                    "started_at": now - timedelta(hours=25),
                },
                "sync_sessions_incremental": {
                    "status": "success",
                    "started_at": now - timedelta(hours=1),
                },
                "sync_operations_incremental": {
                    "status": "success",
                    "started_at": now - timedelta(hours=1),
                },
            }
        },
        problem_jobs=[],
        stuck_mailings=[],
        now=now,
    )

    assert len(alerts) == 1
    assert alerts[0]["code"] == "sync_stale"
    assert alerts[0]["job_type"] == "sync_guests_incremental"


def test_build_operational_alerts_reports_problem_jobs_and_stuck_mailings():
    now = datetime(2026, 6, 30, 12, 0, 0)
    alerts = operational_alerts.build_operational_alerts(
        clubs=[],
        latest_jobs_by_club={},
        problem_jobs=[{
            "id": 4,
            "club_id": 2,
            "job_type": "process_mailing",
            "status": "error",
            "started_at": now - timedelta(minutes=20),
            "error_text": "telegram failed",
        }],
        stuck_mailings=[{
            "id": 15,
            "club_id": 2,
            "status": "in_progress",
            "activity_at": now - timedelta(minutes=90),
            "recipients_count": 100,
        }],
        now=now,
    )

    assert [alert["code"] for alert in alerts] == ["background_job_failed", "mailing_stuck"]
    assert all(alert["severity"] == "error" for alert in alerts)
    assert alerts[1]["metadata"]["mailing_id"] == 15


def test_fetch_problem_jobs_only_considers_latest_job_per_club_and_type():
    class Cursor:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=None):
            self.executed.append((query, params))

        def fetchall(self):
            return []

    cursor = Cursor()
    rows = operational_alerts._fetch_problem_jobs(cursor, limit=20)

    assert rows == []
    problem_query = cursor.executed[-1][0]
    assert "MAX(started_at) AS latest_started_at" in problem_query
    assert "GROUP BY club_id, job_type" in problem_query
    assert "WHERE r.status IN ('error', 'stale')" in problem_query


def test_build_operational_alerts_reports_backup_problem():
    alerts = operational_alerts.build_operational_alerts(
        clubs=[],
        latest_jobs_by_club={},
        problem_jobs=[],
        stuck_mailings=[],
        backup_status={
            "status": "error",
            "message": "Последний backup старше 24 ч",
            "age_hours": 48,
            "max_age_hours": 24,
            "configured_dirs": ["/var/backups/cm"],
            "latest": {"name": "old.sql.gz", "path": "/var/backups/cm/old.sql.gz"},
        },
        now=datetime(2026, 7, 1, 12, 0, 0),
    )

    assert len(alerts) == 1
    assert alerts[0]["code"] == "backup_stale"
    assert alerts[0]["severity"] == "error"
    assert alerts[0]["age_minutes"] == 48 * 60


def test_summarize_alerts_counts_severity():
    summary = operational_alerts.summarize_alerts([
        {"severity": "error"},
        {"severity": "warning"},
        {"severity": "warning"},
    ])

    assert summary == {"error": 1, "warning": 2, "info": 0, "total": 3}
