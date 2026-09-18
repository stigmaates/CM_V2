import importlib

from flask import render_template

from app.main import app


def test_maintenance_migration_exports_settings_table():
    migration = importlib.import_module("migrations.versions.0047_maintenance_mode")

    assert migration.revision == "0047_maintenance_mode"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "module_maintenance_settings" in value
        for value in migration.upgrade.__code__.co_consts
    )


def test_maintenance_gate_blocks_owner(monkeypatch):
    import app.core as core
    import app.services.maintenance as maintenance

    flask_app = core.create_flask_app()

    @flask_app.get("/owner/dashboard")
    def owner_dashboard():
        return "owner ok"

    monkeypatch.setattr(core, "is_club_service_enabled", lambda club_id: True)
    monkeypatch.setattr(maintenance, "is_maintenance_enabled", lambda club_id: True)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "owner"
        sess["club_id"] = 7
        sess["club_name"] = "Test Club"

    response = client.get("/owner/dashboard")

    assert response.status_code == 503
    assert "Ведутся технические работы" in response.get_data(as_text=True)
    assert "скоро все заработает, как раньше =)" in response.get_data(as_text=True)


def test_maintenance_gate_blocks_guest_json(monkeypatch):
    import app.core as core
    import app.services.maintenance as maintenance

    flask_app = core.create_flask_app()

    @flask_app.get("/guest/api/tokens")
    def guest_tokens():
        return {"ok": True}

    monkeypatch.setattr(core, "is_club_service_enabled", lambda club_id: True)
    monkeypatch.setattr(maintenance, "is_maintenance_enabled", lambda club_id: True)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["guest_id"] = 99
        sess["guest_logged_in"] = True
        sess["guest_club_id"] = 7

    response = client.get("/guest/api/tokens", headers={"Accept": "application/json"})

    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "error": "maintenance_mode"}


def test_maintenance_gate_never_blocks_admin(monkeypatch):
    import app.core as core
    import app.services.maintenance as maintenance

    flask_app = core.create_flask_app()

    @flask_app.get("/admin/dashboard")
    def admin_dashboard():
        return "admin ok"

    monkeypatch.setattr(maintenance, "is_maintenance_enabled", lambda club_id: True)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
        sess["club_id"] = 7

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "admin ok"


def test_admin_clubs_template_has_global_and_club_controls():
    with app.test_request_context("/admin/clubs"):
        html = render_template(
            "admin/clubs.html",
            clubs=[
                {
                    "club_id": 1,
                    "name": "Cyber Club",
                    "owner_name": "Owner",
                    "owner_login": "owner",
                    "service_enabled": 1,
                    "maintenance_enabled": 1,
                    "guests_count": 42,
                    "telegram_guests_count": 17,
                }
            ],
            global_maintenance_enabled=False,
            active_page="clubs",
        )

    assert "Технические работы во всех клубах" in html
    assert 'id="globalMaintenanceToggle"' in html
    assert 'id="clubMaintenanceToggle"' in html
    assert "/admin/clubs/maintenance" in html
    assert "/admin/clubs/${currentClubId}/maintenance" in html
    assert "Включены" in html
