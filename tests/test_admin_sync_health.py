from app.routes.admin import dashboard as admin_dashboard


def test_overall_sync_status_prioritizes_errors():
    jobs = [
        {"status": "success"},
        {"status": "running"},
        {"status": "error"},
    ]

    assert admin_dashboard._overall_sync_status(jobs) == "error"


def test_overall_sync_status_marks_missing_data_as_stale():
    jobs = [
        {"status": "success"},
        {"status": "none"},
        {"status": "success"},
    ]

    assert admin_dashboard._overall_sync_status(jobs) == "stale"


def test_summarize_sync_health_counts_club_states():
    summary = admin_dashboard.summarize_sync_health([
        {"overall": "success"},
        {"overall": "success"},
        {"overall": "stale"},
        {"overall": "error"},
        {"overall": "running"},
    ])

    assert summary == {
        "success": 2,
        "stale": 1,
        "error": 1,
        "running": 1,
        "total": 5,
    }
