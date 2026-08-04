from app.main import app
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
    summary = admin_dashboard.summarize_sync_health(
        [
            {"overall": "success"},
            {"overall": "success"},
            {"overall": "stale"},
            {"overall": "error"},
            {"overall": "running"},
            {"overall": "disabled"},
        ]
    )

    assert summary == {
        "success": 2,
        "stale": 1,
        "error": 1,
        "running": 1,
        "disabled": 1,
        "total": 6,
    }


def test_get_club_sync_health_marks_disabled_clubs_without_jobs(monkeypatch):
    monkeypatch.setattr(admin_dashboard, "get_latest_job_runs_by_club", lambda job_types: {})

    health = admin_dashboard.get_club_sync_health(
        [
            {"club_id": 7, "name": "Paused", "service_enabled": 0},
        ]
    )

    assert health == [
        {
            "club_id": 7,
            "name": "Paused",
            "overall": "disabled",
            "jobs": [],
        }
    ]


def test_clubs_list_does_not_create_log_tables_on_page_load(monkeypatch):
    called = []

    monkeypatch.setattr(admin_dashboard, "get_clubs_for_admin", lambda: [])
    monkeypatch.setattr(admin_dashboard, "ensure_admin_sync_logs_table", lambda: called.append("sync"))
    monkeypatch.setattr(
        admin_dashboard, "ensure_admin_impersonation_logs_table", lambda: called.append("impersonation")
    )
    monkeypatch.setattr(admin_dashboard, "render_template", lambda template, **context: (template, context))

    with app.test_request_context("/admin/clubs"):
        template, context = admin_dashboard.clubs_list.__wrapped__()

    assert template == "admin/clubs.html"
    assert context["clubs"] == []
    assert called == []
