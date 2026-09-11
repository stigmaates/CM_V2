"""Inspect or install the stage data mirror. Never changes production services or files."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_ROOT = Path("/root/cm_stage/CM_V2")
PROD_ROOT = Path("/root/cm_v2/CM_V2")
MIRROR_SERVICE = "clubmodule-stage-data-mirror.service"
MIRROR_TIMER = "clubmodule-stage-data-mirror.timer"
WEB_SERVICE = "clubmodule-stage.service"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def contains_root(text, root):
    return bool(re.search(re.escape(str(root)) + r"(?=[/\s;'\"\)]|$)", text))


def filtered_cron(content):
    lines, count = [], 0
    for line in content.splitlines(keepends=True):
        if not line.lstrip().startswith("#") and contains_root(line, STAGE_ROOT):
            if contains_root(line, PROD_ROOT):
                raise ValueError("A cron line combines stage and production; split it before setup")
            if "/scripts/backup_mysql.sh" not in line:
                line = "# stage mirror disabled legacy job: " + line
                count += 1
        lines.append(line)
    return "".join(lines), count


def cron_plan():
    root = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if root.returncode not in (0, 1):
        raise ValueError("Cannot inspect root crontab")
    result = [(None, root.stdout, *filtered_cron(root.stdout))]
    files = [Path("/etc/crontab")]
    directory = Path("/etc/cron.d")
    if directory.exists():
        files += [p for p in directory.iterdir() if p.is_file()]
    for path in files:
        if path.exists():
            content = path.read_text()
            result.append((path, content, *filtered_cron(content)))
    return result


def parse_properties(text):
    return [dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            for block in text.strip().split("\n\n") if block.strip()]


def service_plan():
    # Inspect actual configured units; never infer a production service from its name.
    listing = run("systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager", capture_output=True)
    names = [line.split()[0] for line in listing.stdout.splitlines() if line.strip() and line.split()[0].endswith(".service")]
    details = run("systemctl", "show", *names, "--property=Id,WorkingDirectory,EnvironmentFiles,ExecStart", capture_output=True)
    services = []
    for item in parse_properties(details.stdout):
        content = " ".join(item.values())
        if contains_root(content, STAGE_ROOT):
            if contains_root(content, PROD_ROOT):
                raise ValueError(f"Service combines stage and production: {item['Id']}")
            if "/scripts/backup_mysql.sh" not in content:
                services.append(item["Id"])
        elif item.get("Id") == WEB_SERVICE:
            raise ValueError("Stage web unit does not reference the expected stage checkout")
    if WEB_SERVICE not in services:
        raise ValueError("Verified stage web service was not found")
    listing = run("systemctl", "list-unit-files", "--type=timer", "--no-legend", "--no-pager", capture_output=True)
    timers = []
    for line in listing.stdout.splitlines():
        if not line.strip() or not line.split()[0].endswith(".timer"):
            continue
        name = line.split()[0]
        data = run("systemctl", "show", name, "--property=Triggers", "--value", capture_output=True)
        if set(data.stdout.split()) & set(services):
            timers.append(name)
    return sorted(set(services)), sorted(set(timers))


def assert_stage_idle():
    active = []
    for item in Path("/proc").iterdir():
        if not item.name.isdigit() or int(item.name) == os.getpid():
            continue
        try:
            cwd = (item / "cwd").resolve(strict=True)
            executable = (item / "exe").resolve(strict=True).name.lower()
            command = (item / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (OSError, PermissionError):
            continue
        if (cwd == ROOT or contains_root(command, ROOT)) and ("python" in executable or "gunicorn" in executable):
            active.append(item.name)
    if active:
        raise ValueError("Stage Python jobs still running; let them finish before retrying. PIDs: " + ",".join(active))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Install after read-only checks and stage backup")
    args = parser.parse_args()
    if ROOT.resolve() != STAGE_ROOT.resolve() or os.geteuid() != 0:
        raise ValueError("Run with stage venv as root in /root/cm_stage/CM_V2")
    os.umask(0o077)
    run(sys.executable, str(ROOT / "scripts/mirror_production_to_stage.py"), "--check")
    cron = cron_plan()
    services, timers = service_plan()
    print("Stage services to pause: " + ", ".join(services), flush=True)
    print("Stage timers to disable: " + (", ".join(timers) or "none"), flush=True)
    print(f"Legacy stage cron lines to disable: {sum(row[3] for row in cron)}", flush=True)
    print("New schedule: production data mirror + portraits + Guest Pulse, 5 minutes after each completed run.", flush=True)
    if not args.apply:
        print("Preflight complete. No data, services or schedules changed.")
        return
    backup_dir = ROOT / "backups" / ("mirror-setup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    backup_dir.mkdir(parents=True, mode=0o700)
    (backup_dir / "manifest.json").write_text(json.dumps({
        "cron": {f"cron-{i}.original": str(path) if path else "root crontab"
                 for i, (path, _, _, count) in enumerate(cron) if count},
        "paused_services": services, "disabled_timers": timers,
    }, indent=2) + "\n")
    # Stop switch is local to this checkout and is not overwritten by database copying.
    (ROOT / ".stage-no-outbound").write_text("Outbound messages disabled for production data mirror.\n")
    for index, (path, original, updated, count) in enumerate(cron):
        if count:
            (backup_dir / f"cron-{index}.original").write_text(original)
            if path is None:
                run("crontab", "-", input=updated)
            else:
                path.write_text(updated)
    if timers:
        run("systemctl", "disable", "--now", *timers)
    run("systemctl", "stop", *services)
    legacy = [name for name in services if name not in (WEB_SERVICE, MIRROR_SERVICE)]
    if legacy:
        run("systemctl", "disable", *legacy)
    assert_stage_idle()
    env = os.environ.copy()
    env.update(ENV_FILE=str(ROOT / ".env"), BACKUP_DIR=str(backup_dir), PYTHON_BIN=sys.executable)
    run("bash", str(ROOT / "scripts/backup_mysql.sh"), env=env)
    # Web remains stopped on failure; a partial data transaction never gets published.
    run(sys.executable, str(ROOT / "scripts/mirror_production_to_stage.py"), "--apply", "--reset-pulse-history")
    for name in (MIRROR_SERVICE, MIRROR_TIMER):
        path = Path("/etc/systemd/system") / name
        if path.exists():
            (backup_dir / (name + ".original")).write_bytes(path.read_bytes())
        path.write_bytes((ROOT / "deploy/systemd" / name).read_bytes())
        path.chmod(0o644)
    run("systemctl", "daemon-reload")
    run("systemctl", "start", WEB_SERVICE)
    run("systemctl", "enable", "--now", MIRROR_TIMER)
    run("systemctl", "is-active", WEB_SERVICE, MIRROR_TIMER)
    print(f"Stage mirror installed; outbound stop switch active. Backups: {backup_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Stage setup stopped: {type(exc).__name__}. Production was not modified.", file=sys.stderr)
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
