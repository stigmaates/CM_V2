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
            "TECH_ALERT_BOT_TOKEN": "tech",
            "TECH_ALERT_CHAT_ID": "chat",
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


def test_release_preflight_accepts_isolated_production_storage(monkeypatch):
    monkeypatch.setattr("scripts.check_environment.shutil.which", lambda command: f"/usr/bin/{command}")

    errors, _warnings = validate_env(
        {
            "APP_ENV": "production",
            "APP_VERSION": "2026.09.18",
            "GIT_COMMIT": "4578d18",
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
            "TECH_ALERT_BOT_TOKEN": "tech",
            "TECH_ALERT_CHAT_ID": "chat",
            "CLUBMODULE_UPLOAD_ROOT": "/var/www/uploads/production",
            "ADMIN_FILES_ROOT": "/var/lib/clubmodule/admin-drive",
            "MONTHLY_REPORT_ROOT": "/var/lib/clubmodule/monthly-reports",
            "ADMIN_FILES_MAX_MB": "100",
            "ADMIN_FILES_REQUEST_MAX_MB": "250",
            "STEAM_API_KEY": "steam-key",
            "STEAM_PUBLIC_BASE_URL": "https://cyber-bonus.example",
            "CS2_GC_BRIDGE_URL": "http://127.0.0.1:32173",
            "CS2_GC_BRIDGE_SECRET": "x" * 32,
            "CS2_GC_REFRESH_TOKEN": "refresh-token",
        },
        release_features=True,
    )

    assert errors == []


def test_release_preflight_rejects_stage_and_public_private_paths(monkeypatch):
    monkeypatch.setattr("scripts.check_environment.shutil.which", lambda command: f"/usr/bin/{command}")

    errors, _warnings = validate_env(
        {
            "APP_ENV": "production",
            "APP_VERSION": "release",
            "GIT_COMMIT": "commit",
            "DB_HOST": "db",
            "DB_PORT": "3306",
            "DB_USER": "user",
            "DB_PASSWORD": "password",
            "DB_NAME": "name",
            "SECRET_KEY": "safe-secret",
            "BOT_TOKEN": "token",
            "CLUBMODULE_UPLOAD_ROOT": "/var/www/uploads/stage",
            "ADMIN_FILES_ROOT": "/var/www/uploads/stage/admin",
            "MONTHLY_REPORT_ROOT": "/var/www/uploads/stage/reports",
            "STEAM_API_KEY": "steam-key",
            "STEAM_PUBLIC_BASE_URL": "http://stage.example",
            "CS2_GC_BRIDGE_URL": "https://remote.example",
            "CS2_GC_BRIDGE_SECRET": "short",
            "CS2_GC_REFRESH_TOKEN": "refresh-token",
        },
        release_features=True,
    )

    assert "CLUBMODULE_UPLOAD_ROOT contains a stage path" in errors
    assert "ADMIN_FILES_ROOT must be outside CLUBMODULE_UPLOAD_ROOT" in errors
    assert "MONTHLY_REPORT_ROOT must be outside CLUBMODULE_UPLOAD_ROOT" in errors
    assert "STEAM_PUBLIC_BASE_URL must be an absolute HTTPS origin" in errors
    assert "CS2_GC_BRIDGE_URL must use HTTP on localhost" in errors
    assert "CS2_GC_BRIDGE_SECRET must contain at least 32 characters" in errors
