import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "club_module_bot")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
TG_PROXY_URL = os.getenv("TG_PROXY_URL")
CM_BONUS_BOT_TOKEN = os.getenv("CM_BONUS_BOT_TOKEN", "")
CM_BONUS_ADMIN_CHAT_ID = os.getenv("CM_BONUS_ADMIN_CHAT_ID", "")

AUTO_MAILING_TIMEZONE = os.getenv("AUTO_MAILING_TIMEZONE", "Europe/Moscow")
