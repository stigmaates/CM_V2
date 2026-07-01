from types import SimpleNamespace

from app.services import service_control


def test_get_restart_controls_requires_enabled_flag(monkeypatch):
    monkeypatch.setattr(service_control, "ADMIN_SERVICE_RESTART_ENABLED", False)
    monkeypatch.setattr(service_control, "ADMIN_RESTART_SERVICES", "clubmodule-stage.service:Stage Web")

    controls = service_control.get_restart_controls()

    assert controls["enabled"] is False
    assert controls["available"] is False
    assert controls["targets"] == [{"name": "clubmodule-stage.service", "label": "Stage Web"}]


def test_restart_allowed_service_rejects_unknown_service(monkeypatch):
    monkeypatch.setattr(service_control, "ADMIN_SERVICE_RESTART_ENABLED", True)
    monkeypatch.setattr(service_control, "ADMIN_RESTART_SERVICES", "clubmodule-stage.service:Stage Web")

    result = service_control.restart_allowed_service("clubmodule.service")

    assert result["ok"] is False
    assert result["error"] == "service_not_allowed"


def test_restart_allowed_service_queues_systemctl_restart(monkeypatch):
    calls = []
    monkeypatch.setattr(service_control, "ADMIN_SERVICE_RESTART_ENABLED", True)
    monkeypatch.setattr(service_control, "ADMIN_RESTART_SERVICES", "clubmodule-stage.service:Stage Web")
    monkeypatch.setattr(service_control.shutil, "which", lambda command: f"/usr/bin/{command}")

    def fake_run(cmd, capture_output, check, text, timeout):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_control.subprocess, "run", fake_run)

    result = service_control.restart_allowed_service("clubmodule-stage.service")

    assert result["ok"] is True
    assert calls == [["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "--no-block", "restart", "clubmodule-stage.service"]]


def test_restart_allowed_service_falls_back_when_sudo_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(service_control, "ADMIN_SERVICE_RESTART_ENABLED", True)
    monkeypatch.setattr(service_control, "ADMIN_RESTART_SERVICES", "clubmodule-stage.service:Stage Web")
    def fake_which(command):
        if command in {"systemctl", "/usr/bin/systemctl"}:
            return "/usr/bin/systemctl"
        return None

    monkeypatch.setattr(service_control.shutil, "which", fake_which)

    def fake_run(cmd, capture_output, check, text, timeout):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_control.subprocess, "run", fake_run)

    result = service_control.restart_allowed_service("clubmodule-stage.service")

    assert result["ok"] is True
    assert calls == [["/usr/bin/systemctl", "--no-block", "restart", "clubmodule-stage.service"]]


def test_restart_allowed_service_reports_missing_systemctl(monkeypatch):
    monkeypatch.setattr(service_control, "ADMIN_SERVICE_RESTART_ENABLED", True)
    monkeypatch.setattr(service_control, "ADMIN_RESTART_SERVICES", "clubmodule-stage.service:Stage Web")
    monkeypatch.setattr(service_control.shutil, "which", lambda command: None)

    result = service_control.restart_allowed_service("clubmodule-stage.service")

    assert result["ok"] is False
    assert "systemctl binary not found" in result["error"]
