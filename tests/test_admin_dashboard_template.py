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


def test_admin_dashboard_renders_disabled_sync_summary():
    with app.test_request_context("/admin/dashboard"):
        html = render_template(
            "admin/dashboard.html",
            metrics={
                "clubs_count": 1,
                "users_count": 1,
                "owners_count": 1,
                "admins_count": 1,
            },
            recent_clubs=[],
            club_sync_health=[{"club_id": 2, "name": "Paused", "overall": "disabled", "jobs": []}],
            sync_health_summary={"success": 0, "stale": 0, "error": 0, "running": 0, "disabled": 1},
            operational_alerts=[],
            operational_alert_summary={"error": 0, "warning": 0},
            recent_job_runs=[],
            system_health={},
            readiness={
                "overall_status": "success",
                "overall_label": "Готово",
                "environment": "stage",
                "release": {"commit": "abcdef1"},
                "items": [],
            },
            restart_controls={"enabled": False, "available": False, "targets": []},
            active_page="dashboard",
        )

    assert "Выключено" in html
    assert "Фоновые синхронизации не учитываются" in html


def test_admin_users_page_renders_selected_user_card():
    with app.test_request_context("/admin/users?user_id=7"):
        html = render_template(
            "admin/users.html",
            users=[
                {
                    "user_id": 7,
                    "role": "owner",
                    "name": "Иван Иванов",
                    "login": "ivan",
                    "club_id": 1,
                    "club_name": "Cyber Club",
                    "created_at": None,
                    "last_login_at": None,
                }
            ],
            selected_user={
                "user_id": 7,
                "role": "owner",
                "name": "Иван Иванов",
                "login": "ivan",
                "club_id": 1,
                "club_name": "Cyber Club",
                "created_at": None,
                "last_login_at": None,
            },
            active_page="users",
        )

    assert "Пользователи" in html
    assert "Иван Иванов" in html
    assert "@ivan" in html
    assert "Последний вход" in html
    assert "Сбросить пароль" in html
    assert "/admin/users/7/reset-password" in html


def test_admin_clubs_page_renders_service_toggle():
    with app.test_request_context("/admin/clubs"):
        html = render_template(
            "admin/clubs.html",
            clubs=[
                {
                    "club_id": 1,
                    "name": "Cyber Club",
                    "owner_name": "Owner",
                    "owner_login": "owner",
                    "service_enabled": 0,
                    "created_at": None,
                }
            ],
            active_page="clubs",
        )

    assert "Обслуживание клуба" in html
    assert "Выключено" in html
    assert "clubServiceToggle" in html
    assert "Тестовый гость" in html
    assert "Открыть как гость" in html
    assert "/admin/clubs/${club.club_id}/guest-test" in html
