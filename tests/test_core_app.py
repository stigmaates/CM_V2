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
