from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: int | None = None
    message: str = ""


def _fetch_json(url: str, timeout: int) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "cyber-bonus-smoke/1.0"})
    with urlopen(request, timeout=timeout) as response:
        status = int(response.status)
        payload = response.read().decode("utf-8")
    return status, json.loads(payload)


def _check_endpoint(base_url: str, path: str, timeout: int, expected_version: str | None = None) -> CheckResult:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        status, data = _fetch_json(url, timeout)
    except HTTPError as exc:
        return CheckResult(path, False, exc.code, f"HTTP {exc.code}")
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return CheckResult(path, False, None, str(exc))

    if status != 200:
        return CheckResult(path, False, status, f"unexpected status {status}")
    if data.get("ok") is not True:
        return CheckResult(path, False, status, f"ok is not true: {data}")
    if expected_version and data.get("version") != expected_version:
        return CheckResult(path, False, status, f"version mismatch: {data.get('version')!r}")

    return CheckResult(path, True, status, "ok")


def run_checks(
    *,
    base_url: str,
    timeout: int,
    skip_ready: bool = False,
    expected_version: str | None = None,
) -> list[CheckResult]:
    checks = [_check_endpoint(base_url, "/healthz", timeout, expected_version)]
    if not skip_ready:
        checks.append(_check_endpoint(base_url, "/readyz", timeout, expected_version))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HTTP smoke checks against Cyber Bonus.")
    parser.add_argument("--base-url", required=True, help="Base URL, for example https://staging.example.com")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument(
        "--skip-ready", action="store_true", help="Skip /readyz when database is intentionally unavailable"
    )
    parser.add_argument("--expected-version", help="Expected APP_VERSION returned by health endpoints")
    args = parser.parse_args(argv)

    results = run_checks(
        base_url=args.base_url,
        timeout=args.timeout,
        skip_ready=args.skip_ready,
        expected_version=args.expected_version,
    )

    failed = False
    for result in results:
        marker = "OK" if result.ok else "FAIL"
        print(f"{marker} {result.name}: {result.message}")
        failed = failed or not result.ok

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
