from scripts import delayed_systemctl_restart


def test_delayed_systemctl_restart_runs_command(monkeypatch):
    calls = []

    monkeypatch.setattr(delayed_systemctl_restart.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(
        delayed_systemctl_restart.subprocess,
        "run",
        lambda command, check: calls.append(("run", command, check)) or type("Result", (), {"returncode": 0})(),
    )

    result = delayed_systemctl_restart.main(["2", "/usr/bin/systemctl", "restart", "demo.service"])

    assert result == 0
    assert calls == [
        ("sleep", 2.0),
        ("run", ["/usr/bin/systemctl", "restart", "demo.service"], False),
    ]
