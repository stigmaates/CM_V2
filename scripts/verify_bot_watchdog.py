"""Live read-only heartbeat check plus isolated recovery-policy acceptance."""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.bot_health import HEALTH_DIR, boot_id, read_json
from app.services.bot_watchdog import run_check
from scripts.check_guest_bot_health import service_state, target


def verify_policy():
    calls = []
    saved = []
    snapshot = dict(active="active", pid=42, uptime=900)

    def run(state, now, heartbeat=None, service=snapshot):
        return run_check(
            state,
            heartbeat or {},
            service,
            now=now,
            monotonic=1000,
            boot="test",
            notify=lambda code, text: calls.append(("notify", code)) or True,
            restart=lambda: calls.append(("restart",)),
            persist=lambda value: saved.append(dict(value)),
        )

    state = run({}, 10000)
    assert calls[-1] == ("restart",) and saved[-1]["restarts"] == [10000]
    calls.clear()
    state = run(state, 10060)
    assert ("restart",) not in calls
    state = run(state, 10600)
    assert state["restarts"] == [10000, 10600]
    calls.clear()
    state = run(state, 11200)
    assert ("restart",) not in calls
    calls.clear()
    state = run(state, 11260, dict(pid=42, boot_id="test", last_poll_success=995))
    assert state["status"] == "healthy" and ("notify", "bot_recovered") in calls
    calls.clear()
    run(state, 11320, service=dict(snapshot, active="inactive"))
    assert not calls
    return dict(
        stale_poll_detected=True,
        recovery_limit_verified=True,
        recovery_notice_verified=True,
        manual_stop_respected=True,
        real_restarts_in_policy_test=0,
        real_messages_sent=0,
    )


def main():
    unit = target()
    deadline = time.monotonic() + 90
    while True:
        state = service_state(unit)
        heartbeat = read_json(HEALTH_DIR / "guest.json")
        age = time.monotonic() - heartbeat.get("last_poll_success", 0)
        if (
            state["active"] == "active"
            and heartbeat.get("pid") == state["pid"]
            and heartbeat.get("boot_id") == boot_id()
            and 0 <= age < 70
        ):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("No fresh successful Telegram poll from the current bot process")
        time.sleep(5)
    print(
        json.dumps(
            dict(
                status="complete",
                read_only=True,
                unit=unit,
                pid=state["pid"],
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                last_poll_age_seconds=round(age, 2),
                policy=verify_policy(),
                limitation="Live polling verified; recovery decisions simulated without interrupting a working bot.",
            ),
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
