"""A checkout-local stop switch for every outbound message path on the stage mirror."""

import os
from pathlib import Path

STOP_FILE = Path(__file__).resolve().parents[2] / ".stage-no-outbound"
BLOCKED_MESSAGE = "Исходящие сообщения отключены на тестовом стенде"


def outbound_blocked():
    return STOP_FILE.exists() or os.getenv("DISABLE_OUTBOUND_MESSAGES", "").strip().lower() in {"1", "true", "yes"}


def ensure_outbound_allowed():
    if outbound_blocked():
        raise ValueError(BLOCKED_MESSAGE)
