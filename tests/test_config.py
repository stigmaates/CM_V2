import importlib


def test_development_secret_key_fallback(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    import app.config as config

    config = importlib.reload(config)
    assert config.SECRET_KEY == "development-only-change-me"
    assert config.IS_PRODUCTION is False


def test_production_requires_critical_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "BOT_TOKEN", "SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)

    import app.config as config

    try:
        importlib.reload(config)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("production config must reject missing critical variables")

    assert "Missing required production environment variables" in message
    assert "SECRET_KEY" in message


def test_production_config_accepts_required_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "BOT_TOKEN", "SECRET_KEY"):
        monkeypatch.setenv(name, "set")

    import app.config as config

    config = importlib.reload(config)
    assert config.IS_PRODUCTION is True
    assert config.SECRET_KEY == "set"
