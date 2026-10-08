"""Private, payload-free bot health and bounded recovery decisions."""

import json
import math
import os
import tempfile
import time
from pathlib import Path

STALE_SECONDS = 180
RESTART_GAP = 600
RESTART_WINDOW = 3600
MAX_RESTARTS = 2
HEALTH_DIR = Path(__file__).resolve().parents[2] / "instance" / "bot-health"


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except FileNotFoundError:
        return "local-development"


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".health-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def diagnose(data, *, pid, uptime, now, boot):
    """No incoming messages is healthy; stale successful polling is not."""
    if uptime < STALE_SECONDS:
        return None
    if data.get("pid") != pid or data.get("boot_id") != boot:
        return "bot_heartbeat_missing"
    for key in ("last_poll_success", "started_at", "handler_started_at", "last_handler_finished", "queued_updates"):
        value = data.get(key)
        if value is not None and (not isinstance(value, (float, int)) or not math.isfinite(value)):
            return "bot_heartbeat_invalid"
    last_poll = data.get("last_poll_success", data.get("started_at", 0))
    if not isinstance(last_poll, (float, int)) or last_poll > now or now - last_poll >= STALE_SECONDS:
        return "bot_polling_stalled"
    handler = data.get("handler_started_at")
    if handler is not None and now - handler >= STALE_SECONDS:
        return "bot_handler_stalled"
    if (
        data.get("queued_updates", 0) > 0
        and now - data.get("last_handler_finished", data.get("started_at", 0)) >= STALE_SECONDS
    ):
        return "bot_queue_stalled"
    return None


def recovery_allowed(history, *, now):
    recent = [at for at in history if now - RESTART_WINDOW < at <= now]
    allowed = len(recent) < MAX_RESTARTS and (not recent or now - max(recent) >= RESTART_GAP)
    return allowed, recent


class Heartbeat:
    def __init__(self, path=HEALTH_DIR / "guest.json", *, clock=time.monotonic, boot=None):
        self.path = path
        self.clock = clock
        self.queue_size = lambda: 0
        self.data = dict(pid=os.getpid(), boot_id=boot if boot is not None else boot_id(), started_at=clock())

    def save(self):
        self.data.update(sampled_at=self.clock(), queued_updates=self.queue_size())
        try:
            atomic_write(self.path, self.data)
        except OSError:
            # Monitoring must never prevent guest processing. Missing heartbeat is an alert.
            import logging

            logging.error("Cannot write bot health file")

    def poll_success(self):
        self.data.update(last_poll_success=self.clock(), last_poll_error=None)
        self.save()

    def poll_error(self, kind):
        self.data.update(last_poll_error=kind, last_poll_error_at=self.clock())
        self.save()

    def handler_started(self):
        self.data["handler_started_at"] = self.clock()
        self.save()

    def handler_finished(self):
        self.data.update(handler_started_at=None, last_handler_finished=self.clock())
        self.save()
