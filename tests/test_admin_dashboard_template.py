from flask import render_template

from app.main import app


def test_admin_dashboard_renders_readiness_items():
    with app.test_request_context("/admin/dashboard"):
        html = render_template(
            "admin/dashboard.html",
            metrics={
                "clubs_count": 1,
                "users_count": 2,
                "owners_count": 1,
                "admins_count": 1,
            },
            recent_clubs=[],
            club_sync_health=[],
            sync_health_summary={"success": 0, "stale": 0, "error": 0, "running": 0},
            operational_alerts=[],
            operational_alert_summary={"error": 0, "warning": 0},
            recent_job_runs=[],
            system_health={},
            readiness={
                "overall_status": "success",
                "overall_label": "Готово",
                "environment": "stage",
                "release": {"commit": "abcdef1"},
                "items": [
                    {
                        "status": "success",
                        "title": "База данных",
                        "message": "Соединение работает",
                    }
                ],
            },
            restart_controls={
                "enabled": True,
                "available": True,
                "targets": [{"name": "clubmodule-stage.service", "label": "Stage Web"}],
            },
            active_page="dashboard",
        )

    assert "Готовность системы" in html
    assert "База данных" in html
    assert "Управление сервисами" in html
