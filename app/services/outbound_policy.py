"""A checkout-local stop switch for every outbound message path on the stage mirror."""

import os
from pathlib import Path

STOP_FILE = Path(__file__).resolve().parents[2] / ".stage-no-outbound"
BLOCKED_MESSAGE = "Исходящие сообщения отключены на тестовом стенде"
ADMIN_BOT_OVERRIDE_ENV = "ALLOW_STAGE_ADMIN_BOT"


def _enabled(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def outbound_blocked():
    return STOP_FILE.exists() or _enabled(os.getenv("DISABLE_OUTBOUND_MESSAGES"))


def ensure_outbound_allowed():
    if outbound_blocked():
        raise ValueError(BLOCKED_MESSAGE)


def ensure_admin_bot_allowed():
    """Allow only the interactive stage admin bot under an explicit unit-level override."""
    if _enabled(os.getenv(ADMIN_BOT_OVERRIDE_ENV)):
        return
    ensure_outbound_allowed()
