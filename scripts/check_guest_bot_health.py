"""Run outside the bot every minute; never consume or discard Telegram updates."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import APP_ENV, BOT_TOKEN, TG_PROXY_URL
from app.integrations.stage import STAGE_ROOT, require_stage_environment
from app.services.bot_health import HEALTH_DIR, atomic_write, boot_id, diagnose, read_json
from app.services.bot_watchdog import run_check


def target():
    if Path.cwd() != ROOT:
        raise ValueError("Watchdog requires the matching stage/production checkout")
    if ROOT == STAGE_ROOT:
        # Stage uses a mirror marker and a distinct database, not APP_ENV='stage'.
        require_stage_environment()
        return "clubmodule-stage-bot.service"
    if ROOT == Path("/root/cm_v2/CM_V2") and APP_ENV == "production" and not (ROOT / ".stage-no-outbound").exists():
        return "clubmodule-bot.service"
    raise ValueError("Watchdog requires the matching stage/production checkout")


def service_state(unit):
    result = subprocess.check_output(
        [
            "systemctl",
            "show",
            unit,
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
            "-p",
            "ActiveEnterTimestampMonotonic",
            "-p",
            "WorkingDirectory",
        ],
        text=True,
        timeout=10,
    )
    fields = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
    if fields.get("WorkingDirectory") != str(ROOT):
        raise ValueError("Unexpected bot service directory")
    return dict(
        active=fields["ActiveState"],
        pid=int(fields.get("MainPID") or 0),
        uptime=max(0, time.monotonic() - int(fields.get("ActiveEnterTimestampMonotonic") or 0) / 1e6),
    )


def pending_updates():
    import httpx

    try:
        with httpx.Client(proxy=TG_PROXY_URL or None, timeout=8) as client:
            response = client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo")
        data = response.json()
        if response.status_code != 200 or not data.get("ok"):
            return {"probe_error": "telegram_api_error"}
        return {
            "pending_updates": data["result"]["pending_update_count"],
            "webhook_enabled": bool(data["result"].get("url")),
        }
    except Exception as exc:
        return {"probe_error": type(exc).__name__}


def bounded_probe():
    try:
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--probe-only"],
            capture_output=True,
            text=True,
            timeout=12,
            cwd=ROOT,
        )
        return json.loads(child.stdout) if child.returncode == 0 else {"probe_error": "probe_failed"}
    except (subprocess.TimeoutExpired, ValueError):
        return {"probe_error": "probe_timeout_or_invalid_result"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    unit = target()
    if args.probe_only:
        print(json.dumps(pending_updates()))
        return
    if not args.dry_run and os.getenv("BOT_WATCHDOG_ENABLED") != "1":
        raise ValueError("BOT_WATCHDOG_ENABLED=1 is required for recovery")
    if args.dry_run:
        service = service_state(unit)
        issue = diagnose(
            read_json(HEALTH_DIR / "guest.json"),
            pid=service["pid"],
            uptime=service["uptime"],
            now=time.monotonic(),
            boot=boot_id(),
        )
        print(json.dumps(dict(read_only=True, service=service, problem=issue, telegram=bounded_probe())))
        return
    HEALTH_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (HEALTH_DIR / "watchdog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        service = service_state(unit)
        # This probe only inspects queue size. It never calls getUpdates or deleteWebhook.
        probe = bounded_probe() if service["active"] == "active" else {}
        state = read_json(HEALTH_DIR / "watchdog.json")

        def persist(value):
            atomic_write(HEALTH_DIR / "watchdog.json", value)

        def notify(code, action):
            from app.services.tech_alerts import format_tech_alert_message

            alert = dict(
                code=code,
                severity="error",
                job_type="guest_telegram_bot",
                message=action,
                metadata={"pending_updates": probe.get("pending_updates")},
            )
            text = format_tech_alert_message(alert)
            if ROOT == STAGE_ROOT:
                # Keep existing stage outbound restrictions; record exercise evidence locally.
                print("STAGE notification suppressed: " + text, flush=True)
                return True
            try:
                # A stuck alert transport must not hold up recovery of the guest bot.
                child = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys,json; from app.services.tech_alerts import send_telegram_message; "
                        'sent,_=send_telegram_message(sys.stdin.read()); print(json.dumps({"sent":sent}))',
                    ],
                    input=text,
                    text=True,
                    capture_output=True,
                    timeout=22,
                    cwd=ROOT,
                )
                sent = child.returncode == 0 and json.loads(child.stdout).get("sent") is True
            except Exception as exc:
                print("Watchdog alert delivery failed: " + type(exc).__name__, flush=True)
                return False
            if not sent:
                print("Watchdog alert delivery failed; retry next minute", flush=True)
            return sent

        old_pid = service["pid"]

        def restart():
            fresh = service_state(unit)
            if fresh["pid"] != old_pid or fresh["active"] not in ("active", "failed"):
                return  # Maintenance or another recovery overtook this observation.
            subprocess.run(["systemctl", "--no-block", "restart", unit], check=True, timeout=10)

        result = run_check(
            state,
            read_json(HEALTH_DIR / "guest.json"),
            service,
            now=time.time(),
            monotonic=time.monotonic(),
            boot=boot_id(),
            notify=notify,
            restart=restart,
            persist=persist,
        )
        result["telegram"] = probe
        persist(result)
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
