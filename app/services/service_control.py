from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from app.config import ADMIN_RESTART_SERVICES, ADMIN_SERVICE_RESTART_ENABLED


SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.(service|timer)$")


@dataclass(frozen=True)
class RestartTarget:
    name: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "label": self.label}


def _parse_restart_services(raw_value: str) -> list[RestartTarget]:
    targets: list[RestartTarget] = []
    seen: set[str] = set()
    for chunk in (raw_value or "").split(","):
        item = chunk.strip()
        if not item:
            continue
        name, _, label = item.partition(":")
        name = name.strip()
        label = label.strip() or name
        if not SERVICE_NAME_RE.match(name) or name in seen:
            continue
        targets.append(RestartTarget(name=name, label=label))
        seen.add(name)
    return targets


def get_restart_targets() -> list[dict[str, str]]:
    return [target.as_dict() for target in _parse_restart_services(ADMIN_RESTART_SERVICES)]


def get_restart_controls() -> dict[str, Any]:
    targets = get_restart_targets()
    return {
        "enabled": bool(ADMIN_SERVICE_RESTART_ENABLED),
        "targets": targets,
        "available": bool(ADMIN_SERVICE_RESTART_ENABLED and targets),
    }


def _systemctl_restart_command(service_name: str) -> list[str]:
    base = ["systemctl", "--no-block", "restart", service_name]
    if shutil.which("sudo"):
        return ["sudo", "-n", *base]
    return base


def restart_allowed_service(service_name: str) -> dict[str, Any]:
    targets = {target.name: target for target in _parse_restart_services(ADMIN_RESTART_SERVICES)}
    if not ADMIN_SERVICE_RESTART_ENABLED:
        return {"ok": False, "service": service_name, "error": "service_restart_disabled"}
    if service_name not in targets:
        return {"ok": False, "service": service_name, "error": "service_not_allowed"}

    try:
        command = _systemctl_restart_command(service_name)
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "service": service_name, "error": "systemctl_timeout"}
    except Exception as exc:
        return {"ok": False, "service": service_name, "error": str(exc)}

    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "").strip() or f"systemctl exited {completed.returncode}"
        return {"ok": False, "service": service_name, "error": error_text}

    return {
        "ok": True,
        "service": service_name,
        "label": targets[service_name].label,
        "message": "restart_queued",
        "command": " ".join(command),
    }
