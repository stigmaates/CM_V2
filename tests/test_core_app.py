import importlib


def test_flask_cookie_security_follows_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "BOT_TOKEN", "SECRET_KEY"):
        monkeypatch.setenv(name, "set")

    import app.config as config
    import app.core as core

    importlib.reload(config)
    core = importlib.reload(core)
    flask_app = core.create_flask_app()

    assert flask_app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert flask_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert flask_app.config["SESSION_COOKIE_SECURE"] is True
    assert flask_app.config["MAX_CONTENT_LENGTH"] > 0


def test_csrf_rejects_unsafe_request_without_token():
    from app.core import create_flask_app

    flask_app = create_flask_app()

    @flask_app.post("/mutate")
    def mutate():
        return {"ok": True}

    client = flask_app.test_client()

    response = client.post("/mutate")

    assert response.status_code == 400


def test_csrf_accepts_unsafe_request_with_header_token():
    from app.core import CSRF_SESSION_KEY, create_flask_app

    flask_app = create_flask_app()

    @flask_app.post("/mutate")
    def mutate():
        return {"ok": True}

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess[CSRF_SESSION_KEY] = "known-token"

    response = client.post("/mutate", headers={"X-CSRFToken": "known-token"})

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_login_required_returns_json_for_json_requests_without_session():
    from app.core import create_flask_app, login_required

    flask_app = create_flask_app()

    @flask_app.get("/private")
    @login_required
    def private():
        return {"ok": True}

    client = flask_app.test_client()
    response = client.get("/private", headers={"Accept": "application/json"})

    assert response.status_code == 401
    assert response.content_type.startswith("application/json")
    assert response.get_json()["error"] == "login_required"


def test_admin_required_returns_json_for_json_requests_without_session():
    from app.core import admin_required, create_flask_app

    flask_app = create_flask_app()

    @flask_app.get("/admin/private")
    @admin_required
    def private_admin():
        return {"ok": True}

    client = flask_app.test_client()
    response = client.get("/admin/private", headers={"Accept": "application/json"})

    assert response.status_code == 401
    assert response.content_type.startswith("application/json")
    assert response.get_json()["error"] == "login_required"


def test_club_service_gate_blocks_owner_when_service_disabled(monkeypatch):
    import app.core as core

    flask_app = core.create_flask_app()

    @flask_app.get("/owner/dashboard")
    def owner_dashboard():
        return "owner ok"

    monkeypatch.setattr(core, "is_club_service_enabled", lambda club_id: False)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "owner"
        sess["club_id"] = 7
        sess["club_name"] = "Test Club"

    response = client.get("/owner/dashboard")

    assert response.status_code == 403
    assert "Пожалуйста, свяжитесь с нами" in response.get_data(as_text=True)


def test_club_service_gate_blocks_co_owner_when_service_disabled(monkeypatch):
    import app.core as core

    flask_app = core.create_flask_app()

    @flask_app.get("/owner/dashboard")
    def owner_dashboard():
        return "owner ok"

    monkeypatch.setattr(core, "is_club_service_enabled", lambda club_id: False)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "co-owner"
        sess["club_id"] = 7
        sess["club_name"] = "Test Club"

    response = client.get("/owner/dashboard")

    assert response.status_code == 403
    assert "Пожалуйста, свяжитесь с нами" in response.get_data(as_text=True)


def test_owner_required_allows_co_owner():
    from app.core import create_flask_app, owner_required

    flask_app = create_flask_app()

    @flask_app.get("/owner/private")
    @owner_required
    def private_owner():
        return "owner ok"

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "co-owner"
        sess["club_id"] = 7

    response = client.get("/owner/private")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "owner ok"


def test_club_service_gate_does_not_block_admin(monkeypatch):
    import app.core as core

    flask_app = core.create_flask_app()

    @flask_app.get("/admin/dashboard")
    def admin_dashboard():
        return "admin ok"

    monkeypatch.setattr(core, "is_club_service_enabled", lambda club_id: False)

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
        sess["club_id"] = 7

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "admin ok"
