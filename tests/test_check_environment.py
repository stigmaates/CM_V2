from scripts.check_environment import validate_env


def test_validate_env_accepts_production_minimum(monkeypatch):
    monkeypatch.setattr("scripts.check_environment.shutil.which", lambda command: f"/usr/bin/{command}")

    errors, warnings = validate_env(
        {
            "APP_ENV": "production",
            "DB_HOST": "db",
            "DB_PORT": "3306",
            "DB_USER": "user",
            "DB_PASSWORD": "password",
            "DB_NAME": "name",
            "SECRET_KEY": "safe-secret",
            "BOT_TOKEN": "token",
            "BOT_USERNAME": "bot",
            "CM_BONUS_BOT_TOKEN": "bonus",
            "CM_BONUS_ADMIN_CHAT_ID": "chat",
            "CLUBMODULE_UPLOAD_ROOT": "/var/www/uploads",
        }
    )

    assert errors == []
    assert warnings == []


def test_validate_env_rejects_unsafe_secret(monkeypatch):
    monkeypatch.setattr("scripts.check_environment.shutil.which", lambda command: f"/usr/bin/{command}")

    errors, warnings = validate_env(
        {
            "APP_ENV": "production",
            "DB_HOST": "db",
            "DB_PORT": "3306",
            "DB_USER": "user",
            "DB_PASSWORD": "password",
            "DB_NAME": "name",
            "SECRET_KEY": "change-me",
            "BOT_TOKEN": "token",
        }
    )

    assert "SECRET_KEY uses an unsafe default value" in errors
    assert any("Recommended variable is empty" in warning for warning in warnings)
