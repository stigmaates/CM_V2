"""A checkout-local stop switch for every outbound message path on the stage mirror."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

STOP_FILE = Path(__file__).resolve().parents[2] / ".stage-no-outbound"
BLOCKED_MESSAGE = "Исходящие сообщения отключены на тестовом стенде"
ADMIN_BOT_OVERRIDE_ENV = "ALLOW_STAGE_ADMIN_BOT"
GUEST_BOT_OVERRIDE_ENV = "ALLOW_STAGE_GUEST_BOT"
MANUAL_MAILING_OVERRIDE_ENV = "ALLOW_STAGE_MANUAL_MAILINGS"
_manual_mailing_override = ContextVar("manual_mailing_outbound", default=False)


def _enabled(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def outbound_blocked():
    return STOP_FILE.exists() or _enabled(os.getenv("DISABLE_OUTBOUND_MESSAGES"))


def ensure_outbound_allowed():
    if _manual_mailing_override.get() and _enabled(os.getenv(MANUAL_MAILING_OVERRIDE_ENV)):
        return
    if outbound_blocked():
        raise ValueError(BLOCKED_MESSAGE)


def manual_mailings_only():
    """True when stage keeps the global stop but permits owner-triggered mailings."""
    return outbound_blocked() and _enabled(os.getenv(MANUAL_MAILING_OVERRIDE_ENV))


@contextmanager
def allow_manual_mailing_outbound():
    """Narrow override for the owner mailing request and its in-process worker."""
    if outbound_blocked() and not _enabled(os.getenv(MANUAL_MAILING_OVERRIDE_ENV)):
        raise ValueError(BLOCKED_MESSAGE)
    token = _manual_mailing_override.set(True)
    try:
        yield
    finally:
        _manual_mailing_override.reset(token)


def ensure_admin_bot_allowed():
    """Allow only the interactive stage admin bot under an explicit unit-level override."""
    if _enabled(os.getenv(ADMIN_BOT_OVERRIDE_ENV)):
        return
    ensure_outbound_allowed()


def ensure_guest_bot_allowed():
    """Allow only the interactive stage guest bot under an explicit unit-level override."""
    if _enabled(os.getenv(GUEST_BOT_OVERRIDE_ENV)):
        return
    ensure_outbound_allowed()
