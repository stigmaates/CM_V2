from scripts import smoke_http


def test_run_checks_calls_health_and_ready(monkeypatch):
    calls = []

    def fake_check(base_url, path, timeout, expected_version=None):
        calls.append((base_url, path, timeout, expected_version))
        return smoke_http.CheckResult(path, True, 200, "ok")

    monkeypatch.setattr(smoke_http, "_check_endpoint", fake_check)

    results = smoke_http.run_checks(
        base_url="https://staging.example.com",
        timeout=3,
        expected_version="v1",
    )

    assert [result.name for result in results] == ["/healthz", "/readyz"]
    assert calls == [
        ("https://staging.example.com", "/healthz", 3, "v1"),
        ("https://staging.example.com", "/readyz", 3, "v1"),
    ]


def test_run_checks_can_skip_ready(monkeypatch):
    calls = []

    def fake_check(base_url, path, timeout, expected_version=None):
        calls.append(path)
        return smoke_http.CheckResult(path, True, 200, "ok")

    monkeypatch.setattr(smoke_http, "_check_endpoint", fake_check)

    results = smoke_http.run_checks(base_url="https://staging.example.com", timeout=3, skip_ready=True)

    assert [result.name for result in results] == ["/healthz"]
    assert calls == ["/healthz"]


def test_check_endpoint_reports_version_mismatch(monkeypatch):
    monkeypatch.setattr(smoke_http, "_fetch_json", lambda url, timeout: (200, {"ok": True, "version": "old"}))

    result = smoke_http._check_endpoint("https://example.com", "/healthz", 3, expected_version="new")

    assert result.ok is False
    assert "version mismatch" in result.message
