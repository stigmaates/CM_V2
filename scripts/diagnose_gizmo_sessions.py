"""Collect session-link diagnostics, without DB access or changes to Gizmo."""

import getpass
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.gizmo import GizmoClient
from app.integrations.gizmo_diagnostics import diagnose


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    key = getpass.getpass("API-ключ Gizmo (ввод скрыт): ")
    directory = Path.home() / "gizmo-stage-check"
    client = GizmoClient(
        address="213.59.152.72",
        server_name="gizmo.local",
        certificate_pem=(directory / "server.pem").read_text(),
        fingerprint="AA:36:45:41:83:DD:89:63:64:48:CA:C2:44:51:35:D7:AE:77:3D:DD:01:90:1F:BC:99:46:58:D5:E1:8A:DC:8A",
        api_key=key,
    )
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = diagnose(client, end - timedelta(days=7), end)
    output = directory / "session_links.json"
    content = json.dumps(result, ensure_ascii=False, indent=2).replace(key.strip(), "[KEY REDACTED]")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content + "\n")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print(f"Диагностика готова: {output}. База модуля не изменялась.")


if __name__ == "__main__":
    main()
