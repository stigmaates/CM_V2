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
