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


def test_get_clubs_for_admin_includes_guest_counts(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.queries = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql):
            self.queries.append(sql)

        def fetchall(self):
            return [
                {
                    "club_id": 1,
                    "name": "Club",
                    "owner_name": "Owner",
                    "guests_count": 42,
                    "telegram_guests_count": 17,
                }
            ]

    class FakeConnection:
        def __init__(self, cursor):
            self.cursor_obj = cursor

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self.cursor_obj

    cursor = FakeCursor()
    monkeypatch.setattr(admin_dashboard, "table_has_column", lambda table, column: column == "service_enabled")
    monkeypatch.setattr(admin_dashboard, "get_db_connection", lambda: FakeConnection(cursor))

    clubs = admin_dashboard.get_clubs_for_admin()

    assert clubs[0]["guests_count"] == 42
    assert clubs[0]["telegram_guests_count"] == 17
    query = cursor.queries[0]
    assert "FROM guests" in query
    assert "telegram_guests_count" in query
    assert "created_at" not in query


def test_club_sync_rejects_disabled_club_before_creating_log(monkeypatch):
    created_logs = []

    monkeypatch.setattr(
        admin_dashboard,
        "get_club_by_id",
        lambda club_id: {"club_id": club_id, "name": "Paused", "service_enabled": 0},
    )
    monkeypatch.setattr(admin_dashboard, "create_sync_log", lambda *args: created_logs.append(args))

    with app.test_request_context("/admin/clubs/7/sync/guests-incremental", method="POST"):
        response, status = admin_dashboard.club_sync.__wrapped__(7, "guests-incremental")

    assert status == 400
    assert response.get_json()["status"] is False
    assert "выключен" in response.get_json()["message"]
    assert created_logs == []


def test_club_sync_queues_background_job(monkeypatch):
    started_threads = []

    class FakeThread:
        def __init__(self, target=None, kwargs=None, daemon=None):
            self.target = target
            self.kwargs = kwargs
            self.daemon = daemon

        def start(self):
            started_threads.append(self)

    monkeypatch.setattr(
        admin_dashboard,
        "get_club_by_id",
        lambda club_id: {"club_id": club_id, "name": "Club", "service_enabled": 1},
    )
    monkeypatch.setattr(admin_dashboard, "create_sync_log", lambda *args, **kwargs: 42)
    monkeypatch.setattr(admin_dashboard, "get_running_sync_log", lambda *args: None)
    monkeypatch.setattr(admin_dashboard, "Thread", FakeThread)
    monkeypatch.setattr(admin_dashboard, "run_guests_incremental_for_club", lambda club_id: "done")

    with app.test_request_context("/admin/clubs/7/sync/guests-incremental", method="POST"):
        response = admin_dashboard.club_sync.__wrapped__(7, "guests-incremental")

    payload = response.get_json()
    assert payload["status"] is True
    assert payload["queued"] is True
    assert payload["log_id"] == 42
    assert len(started_threads) == 1
    assert started_threads[0].kwargs["club_id"] == 7
    assert started_threads[0].kwargs["log_id"] == 42
    assert started_threads[0].daemon is True


def test_club_sync_reuses_running_job(monkeypatch):
    started_threads = []
    created_logs = []

    class FakeThread:
        def __init__(self, target=None, kwargs=None, daemon=None):
            self.target = target
            self.kwargs = kwargs
            self.daemon = daemon

        def start(self):
            started_threads.append(self)

    monkeypatch.setattr(
        admin_dashboard,
        "get_club_by_id",
        lambda club_id: {"club_id": club_id, "name": "Club", "service_enabled": 1},
    )
    monkeypatch.setattr(admin_dashboard, "get_running_sync_log", lambda *args: {"id": 77})
    monkeypatch.setattr(admin_dashboard, "create_sync_log", lambda *args, **kwargs: created_logs.append(args))
    monkeypatch.setattr(admin_dashboard, "Thread", FakeThread)

    with app.test_request_context("/admin/clubs/7/sync/sessions-initial", method="POST"):
        response = admin_dashboard.club_sync.__wrapped__(7, "sessions-initial")

    payload = response.get_json()
    assert payload["status"] is True
    assert payload["queued"] is True
    assert payload["already_running"] is True
    assert payload["log_id"] == 77
    assert created_logs == []
    assert started_threads == []


def test_club_sync_logs_endpoint_returns_json(monkeypatch):
    logs = [{"id": 3, "script_name": "guests", "sync_mode": "incremental", "status": "success"}]

    monkeypatch.setattr(
        admin_dashboard,
        "get_club_by_id",
        lambda club_id: {"club_id": club_id, "name": "Club", "service_enabled": 1},
    )
    monkeypatch.setattr(admin_dashboard, "get_club_sync_logs", lambda club_id: logs)

    with app.test_request_context("/admin/clubs/7/sync-logs"):
        response = admin_dashboard.club_sync_logs.__wrapped__(7)

    assert response.get_json() == {"status": True, "logs": logs}
