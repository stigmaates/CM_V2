"""Save a Gizmo pilot credential locally on stage; never in Git or module DB."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import get_db_connection
from app.integrations.gizmo import GizmoClient, GizmoError
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, read_target, run_lock
from app.integrations.stage import require_stage_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int, required=True)
    parser.add_argument("--pause", action="store_true")
    args = parser.parse_args()
    require_stage_environment()
    if not DIRECTORY.is_dir() or DIRECTORY.is_symlink():
        raise GizmoError("Missing trusted Gizmo certificate directory")
    with run_lock(DIRECTORY / f"sync-{args.club_id}.lock"):
        path = DIRECTORY / f"sync-{args.club_id}.json"
        if args.pause:
            data = private_json(path)
            data["enabled"] = False
        else:
            conn = get_db_connection()
            try:
                settings = read_target(conn, args.club_id)
            finally:
                conn.close()
            key = getpass.getpass("API-ключ Gizmo для автоматической синхронизации (ввод скрыт): ").strip()
            source = settings["source"]
            existing = private_json(path) if path.exists() else {}
            certificate_pem = existing.get("certificate_pem") or (DIRECTORY / "server.pem").read_text()
            client = GizmoClient(
                address=source["address"],
                server_name=source["server_name"],
                fingerprint=source["fingerprint"],
                certificate_pem=certificate_pem,
                api_key=key,
            )
            client.get("system/version")
            data = {"enabled": True, "api_key": key, "certificate_pem": certificate_pem}
        atomic_json(path, data)
    print(
        "Синхронизация приостановлена."
        if args.pause
        else "Ключ проверен и сохранён на сервере в отдельном файле 0600. Обслуживание клуба не включалось."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, (GizmoError, ValueError)) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
