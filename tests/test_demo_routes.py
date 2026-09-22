from app.main import app
from app.services.guest_pulse_scores import AUDIENCES, SEGMENTS


def test_demo_owner_pages_render_without_authentication():
    app.config.update(TESTING=True)
    client = app.test_client()

    for path, marker in (
        ("/demo", "Оценка первого посещения"),
        ("/demo/cases", "Добавить кейс"),
        ("/demo/guest-pulse", "Отклонения от нормы"),
        ("/demo/cohorts", "Период воронки"),
        ("/demo/communications", "Аналитика коммуникаций"),
        ("/demo/heatmaps", "Тепловая карта по ПК"),
        ("/demo/promotions", "Настройте бонусы за пополнение"),
        ("/demo/team", "Возвращаемость новых гостей"),
        ("/demo/mailings", "Ручная рассылка"),
        ("/demo/missions", "Задания клуба"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert marker in html
        assert "ДЕМО-РЕЖИМ" in html
        assert 'href="/demo/' in html


def test_demo_guest_case_opening_uses_session_balance_only():
    app.config.update(TESTING=True)
    client = app.test_client()

    page = client.get("/demo/guest")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Кабинет гостя" in html
    assert "WALLZ CS2 Case" in html
    assert "502ed09c17c44892b9fb50c131ea8260.webp" in html
    assert "DONKED" in html
    assert "Трудимся в компах" in html
    assert "Игровые контракты" in html
    assert "/static/images/contracts/" in html or "/static/images/cs2/" in html

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
    assert payload["item"]["name"]

    with client.session_transaction() as demo_session:
        assert demo_session["demo_guest_tokens"] == payload["tokens_after"]


def test_unknown_demo_page_returns_404():
    app.config.update(TESTING=True)
    response = app.test_client().get("/demo/does-not-exist")
    assert response.status_code == 404


def test_demo_guest_pulse_uses_current_audiences_and_icon_keys():
    app.config.update(TESTING=True)
    client = app.test_client()

    page = client.get("/demo/guest-pulse")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'window.GUEST_PULSE_API_BASE = "/demo/api/owner/guest-pulse"' in html
    for label in SEGMENTS.values():
        assert label in html

    response = client.get("/demo/api/owner/guest-pulse")
    assert response.status_code == 200
    payload = response.get_json()
    assert [audience["key"] for audience in payload["audiences"]] == [item[0] for item in AUDIENCES]
    assert [audience["label"] for audience in payload["audiences"]] == [item[1] for item in AUDIENCES]
    assert payload["selected_count"] == sum(audience["count"] for audience in payload["audiences"])
    assert all(guest["name"].startswith("Демо-гость ") for guest in payload["guests"])

    repeated = client.get("/demo/api/owner/guest-pulse").get_json()
    assert repeated["audiences"] == payload["audiences"]
    assert repeated["guests"] == payload["guests"]


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
