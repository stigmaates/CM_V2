import os

from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
APP_VERSION = os.getenv("APP_VERSION", "development")
GIT_COMMIT = os.getenv("GIT_COMMIT", "")

DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "30"))
DB_READ_TIMEOUT = int(os.getenv("DB_READ_TIMEOUT", "300"))
DB_WRITE_TIMEOUT = int(os.getenv("DB_WRITE_TIMEOUT", "300"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "club_module_bot")
SECRET_KEY = os.getenv("SECRET_KEY", "")
TG_PROXY_URL = os.getenv("TG_PROXY_URL")
CM_BONUS_BOT_TOKEN = os.getenv("CM_BONUS_BOT_TOKEN", "")
CM_BONUS_ADMIN_CHAT_ID = os.getenv("CM_BONUS_ADMIN_CHAT_ID", "")
CM_BONUS_PROXY_URL = os.getenv("CM_BONUS_PROXY_URL", "")
TECH_ALERT_BOT_TOKEN = os.getenv("TECH_ALERT_BOT_TOKEN", "")
TECH_ALERT_CHAT_ID = os.getenv("TECH_ALERT_CHAT_ID", "")
TECH_ALERT_PROXY_URL = os.getenv("TECH_ALERT_PROXY_URL", "").strip()
TECH_SUPPORT_CHAT_ID = os.getenv("TECH_SUPPORT_CHAT_ID", "").strip() or TECH_ALERT_CHAT_ID.strip()
ADMIN_SERVICE_RESTART_ENABLED = os.getenv("ADMIN_SERVICE_RESTART_ENABLED", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ADMIN_RESTART_SERVICES = os.getenv("ADMIN_RESTART_SERVICES", "")
BACKUP_MONITOR_DIRS = os.getenv("BACKUP_MONITOR_DIRS", "backups")
BACKUP_MAX_AGE_HOURS = int(os.getenv("BACKUP_MAX_AGE_HOURS", "24"))
BALANCE_TOPUP_MAX_AMOUNT = int(os.getenv("BALANCE_TOPUP_MAX_AMOUNT", "100000"))
TOPUP_BONUS_MAX_AMOUNT = int(os.getenv("TOPUP_BONUS_MAX_AMOUNT", "30000"))

AUTO_MAILING_TIMEZONE = os.getenv("AUTO_MAILING_TIMEZONE", "Europe/Moscow")

# Upload storage for owner-managed images (case covers and case prizes).
# For stage use /var/www/clubmodule_uploads/stage, for main set env to /var/www/clubmodule_uploads/main.
CLUBMODULE_UPLOAD_ROOT = os.getenv("CLUBMODULE_UPLOAD_ROOT", "/var/www/clubmodule_uploads/stage")
CLUBMODULE_UPLOAD_URL_PREFIX = os.getenv("CLUBMODULE_UPLOAD_URL_PREFIX", "/uploads")
CLUBMODULE_UPLOAD_QUOTA_MB = int(os.getenv("CLUBMODULE_UPLOAD_QUOTA_MB", "25"))
CLUBMODULE_IMAGE_MAX_MB = int(os.getenv("CLUBMODULE_IMAGE_MAX_MB", "5"))
MONTHLY_REPORT_ROOT = os.getenv(
    "MONTHLY_REPORT_ROOT",
    os.path.join(CLUBMODULE_UPLOAD_ROOT, "monthly_reports"),
)
MONTHLY_REPORT_ATTRIBUTION_DAYS = int(os.getenv("MONTHLY_REPORT_ATTRIBUTION_DAYS", "7"))

# Steam OpenID returns a SteamID64. One server-side Web API key is used only
# for public profile and playtime data; guests never provide their own API key.
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "").strip()
STEAM_PUBLIC_BASE_URL = os.getenv("STEAM_PUBLIC_BASE_URL", "").strip().rstrip("/")
CS2_GC_BRIDGE_URL = os.getenv("CS2_GC_BRIDGE_URL", "").strip().rstrip("/")
CS2_GC_BRIDGE_SECRET = os.getenv("CS2_GC_BRIDGE_SECRET", "").strip()

if IS_PRODUCTION:
    missing = [
        name
        for name, value in {
            "DB_HOST": DB_HOST,
            "DB_USER": DB_USER,
            "DB_PASSWORD": DB_PASSWORD,
            "DB_NAME": DB_NAME,
            "BOT_TOKEN": BOT_TOKEN,
            "SECRET_KEY": SECRET_KEY,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required production environment variables: " + ", ".join(sorted(missing)))

if not SECRET_KEY:
    SECRET_KEY = "development-only-change-me"

# Guest Pulse v1: one rule source for workers, API filters and audience labels.
GUEST_PULSE_CONFIG = {
    "history_days": int(os.getenv("GUEST_PULSE_HISTORY_DAYS", "90")),
    "churn_days": int(os.getenv("GUEST_PULSE_CHURN_DAYS", "60")),
    "healthy_min": float(os.getenv("GUEST_PULSE_HEALTHY_MIN", "80")),
    "stable_min": float(os.getenv("GUEST_PULSE_STABLE_MIN", "60")),
    "at_risk_min": float(os.getenv("GUEST_PULSE_AT_RISK_MIN", "40")),
    "high_risk_min": float(os.getenv("GUEST_PULSE_HIGH_RISK_MIN", "20")),
    "high_value_min": float(os.getenv("GUEST_PULSE_HIGH_VALUE_MIN", "75")),
    "health_drop_alert_14d": float(os.getenv("GUEST_PULSE_HEALTH_DROP_ALERT_14D", "-15")),
}
