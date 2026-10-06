"""Collect a bounded, redacted sample. Never writes Gizmo or the module database."""

import getpass
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.integrations.gizmo import GizmoClient, GizmoError, page_rows

# Values confirmed by the club owner. Key is never stored in this file.
ADDRESS = "213.59.152.72"
SERVER_NAME = "gizmo.local"
FINGERPRINT = "AA:36:45:41:83:DD:89:63:64:48:CA:C2:44:51:35:D7:AE:77:3D:DD:01:90:1F:BC:99:46:58:D5:E1:8A:DC:8A"

SAFE_STRINGS = {
    "starttime",
    "endtime",
    "date",
    "registrationdate",
    "enabledate",
    "disableddate",
    "voiddate",
    "timezone",
    "duration",
    "state",
    "type",
    "sex",
    "amount",
    "balance",
    "id",
    "userid",
    "hostid",
    "branchid",
    "paymentmethodid",
    "number",
    "hostnumber",
    "span",
    "billedspan",
    "totalminutes",
    "value",
    "name",
}


def redact(value, *, directory=False, field=""):
    if isinstance(value, dict):
        return {k: redact(v, directory=directory, field=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, directory=directory, field=field) for v in value[:10]]
    if isinstance(value, str):
        lower = field.lower()
        if lower == "name" and not directory:
            return "[redacted]" if value else ""
        if lower in SAFE_STRINGS or (directory and lower == "hostname"):
            return value
        return "[redacted]" if value else ""
    return value


def main():
    directory = Path.home() / "gizmo-stage-check"
    certificate = directory / "server.pem"
    if not certificate.exists():
        raise SystemExit("Сначала запустите прежний check_connection.py для проверки сертификата.")
    key = getpass.getpass("API-ключ Gizmo (ввод скрыт): ").strip()
    client = GizmoClient(
        address=ADDRESS,
        server_name=SERVER_NAME,
        certificate_pem=certificate.read_text(),
        fingerprint=FINGERPRINT,
        api_key=key,
    )
    output = {"generated_at": datetime.now(UTC).isoformat(), "read_only": True, "samples": {}}
    now = datetime.now(UTC)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    checks = [
        ("system/version", {}),
        ("branches", {"Pagination.Limit": 10}),
        ("hosts", {"Pagination.Limit": 10}),
        ("paymentmethods", {"Pagination.Limit": 10}),
        ("users", {"Pagination.Limit": 3, "IsGuest": "false"}),
        (
            "deposittransactions",
            {"Pagination.Limit": 5, "DateFrom": (now - timedelta(days=7)).isoformat(), "DateTo": now.isoformat()},
        ),
        ("reports/sessionslog", {"DateFrom": start.isoformat(), "DateTo": end.isoformat()}),
        ("usersessions", {"Pagination.Limit": 3, "DateFrom": start.isoformat(), "DateTo": end.isoformat()}),
        ("sessions", {"Pagination.Limit": 3}),
        ("branches/1/timezone", {}),
    ]
    for resource, params in checks:
        print("Чтение " + resource + "...", flush=True)
        try:
            result = client.get(resource, params)
            sample = {"ok": True, "params": params}
            if isinstance(result, dict):
                for field in ("data", "sessions"):
                    if isinstance(result.get(field), list):
                        sample[field + "_count"] = len(result[field])
            sample["result"] = (
                result
                if resource == "system/version"
                else redact(result, directory=resource in ("branches", "hosts", "paymentmethods"))
            )
            if isinstance(result, dict) and isinstance(result.get("nextCursor"), str):
                next_result = client.get(resource, dict(params, **{"Pagination.Cursor": result["nextCursor"]}))
                next_rows = page_rows(next_result)
                sample["second_page"] = redact(
                    next_result, directory=resource in ("hosts", "paymentmethods", "branches")
                )
                sample["second_page_count"] = len(next_rows)
            output["samples"][resource] = sample
            print("OK", flush=True)
        except Exception as exc:
            # No exception/body text from the server: it may contain credentials or PII.
            output["samples"][resource] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc) if isinstance(exc, GizmoError) else type(exc).__name__,
            }
            print("Ошибка: " + (str(exc) if isinstance(exc, GizmoError) else type(exc).__name__), flush=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "discovery.json"
    serialized = json.dumps(output, ensure_ascii=False, indent=2).replace(key, "[KEY REDACTED]")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(serialized + "\n")
    print("Готово: " + str(path))
    print("Это образцы, не полная выгрузка. Имена гостей, телефоны и email скрыты.")


if __name__ == "__main__":
    main()
