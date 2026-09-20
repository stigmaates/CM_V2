from app.main import app


def test_demo_owner_pages_render_without_authentication():
    app.config.update(TESTING=True)
    client = app.test_client()

    for path, marker in (
        ("/demo", "Главные показатели демонстрационного клуба"),
        ("/demo/cases", "Настройка игровых механик и призов"),
        ("/demo/guest-pulse", "Состояние и поведение гостевой базы"),
        ("/demo/cohorts", "Воронка визитов по когорте"),
        ("/demo/heatmaps", "Тепловая карта по ПК"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.get_data(as_text=True)


def test_demo_guest_case_opening_uses_session_balance_only():
    app.config.update(TESTING=True)
    client = app.test_client()

    page = client.get("/demo/guest")
    assert page.status_code == 200
    assert "Демонстрационный профиль" in page.get_data(as_text=True)

    with client.session_transaction() as demo_session:
        csrf_token = demo_session["_csrf_token"]
        assert demo_session["demo_guest_tokens"] == 24

    response = client.post(
        "/demo/guest/cases/1/open",
        headers={"X-CSRFToken": csrf_token, "Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["prize"]["name"]

    with client.session_transaction() as demo_session:
        assert demo_session["demo_guest_tokens"] == payload["tokens"]
        assert len(demo_session["demo_guest_history"]) == 1


def test_unknown_demo_page_returns_404():
    app.config.update(TESTING=True)
    response = app.test_client().get("/demo/does-not-exist")
    assert response.status_code == 404


def test_demo_skips_real_club_checks_for_existing_owner_session(monkeypatch):
    def fail_on_real_data(*args, **kwargs):
        raise AssertionError("demo route tried to read real club data")

    monkeypatch.setattr("app.core.is_club_service_enabled", fail_on_real_data)
    monkeypatch.setattr("app.services.maintenance.is_maintenance_enabled", fail_on_real_data)
    monkeypatch.setattr("app.main.get_db_connection", fail_on_real_data)

    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as owner_session:
        owner_session["role"] = "owner"
        owner_session["club_id"] = 2

    response = client.get("/demo")
    assert response.status_code == 200
    assert "DEMO CLUB" in response.get_data(as_text=True)
