"""Read-only by default. Apply a Gizmo pilot snapshot only to the isolated stage DB."""

import argparse
import getpass
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import get_db_connection
from app.integrations.gizmo import GizmoClient, GizmoError
from app.integrations.gizmo_import import check_target, collect, save
from app.integrations.stage import require_stage_environment
from app.services.timezones import validate_club_timezone

ADDRESS = "213.59.152.72"
FINGERPRINT = "AA:36:45:41:83:DD:89:63:64:48:CA:C2:44:51:35:D7:AE:77:3D:DD:01:90:1F:BC:99:46:58:D5:E1:8A:DC:8A"


def require_stage():
    require_stage_environment()


def provision(conn, name, timezone_name):
    """Create only a disabled pilot; reruns reuse the same club under the mirror lock."""
    with conn.cursor() as cur:
        cur.execute("SELECT GET_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())),0) AS acquired")
        if not (cur.fetchone() or {}).get("acquired"):
            raise GizmoError("Stage mirror/import is running; retry later")
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clubs WHERE integration_provider='gizmo' AND name=%s", (name,))
            matches = cur.fetchall()
            if len(matches) > 1:
                raise GizmoError("Multiple Gizmo clubs with this name; use --club-id")
            if matches:
                check_target(matches[0])
                conn.rollback()
                return int(matches[0]["club_id"])
            # Keep the pilot outside the ordinary low-valued production ID sequence.
            cur.execute("SELECT COALESCE(MAX(CAST(club_id AS UNSIGNED)),0)+1 AS next_id FROM clubs")
            club_id = max(900001, int(cur.fetchone()["next_id"]))
            cur.execute(
                """INSERT INTO clubs (club_id,name,timezone,lg_api_key,secret,owner_id,
                service_enabled,integration_provider,integration_ready)
                VALUES (%s,%s,%s,'','',NULL,0,'gizmo',0)""",
                (club_id, name, timezone_name),
            )
            cur.execute("INSERT INTO club_integrations (club_id) VALUES (%s)", (club_id,))
        conn.commit()
        return club_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())))")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--club-id", type=int)
    group.add_argument("--create-club")
    parser.add_argument("--timezone", default="Asia/Yekaterinburg")
    parser.add_argument("--branch-id", type=int, default=1)
    parser.add_argument("--date-from", required=True, help="UTC date, inclusive, YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="UTC date, exclusive, YYYY-MM-DD")
    parser.add_argument(
        "--cash-methods", required=True, help="Explicit mapped money methods, e.g. --cash-methods=-1,-2"
    )
    parser.add_argument(
        "--without-sessions",
        action="store_true",
        help="Import only guests, equipment and deposits; visits remain unavailable",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    require_stage()
    tz = validate_club_timezone(args.timezone)
    start = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=UTC)
    end = datetime.strptime(args.date_to, "%Y-%m-%d").replace(tzinfo=UTC)
    cash_methods = {int(value) for value in args.cash_methods.split(",")}
    certificate = Path("/root/gizmo-stage-check/server.pem").read_text()
    key = getpass.getpass("API-ключ Gizmo (ввод скрыт): ")
    client = GizmoClient(
        address=ADDRESS, server_name="gizmo.local", certificate_pem=certificate, fingerprint=FINGERPRINT, api_key=key
    )
    print("Читаем Gizmo; база модуля пока не меняется.", flush=True)
    data = collect(
        client,
        branch_id=args.branch_id,
        start=start,
        end=end,
        cash_method_ids=cash_methods,
        include_sessions=not args.without_sessions,
    )
    data["scope"]["source"] = {"address": ADDRESS, "server_name": "gizmo.local", "fingerprint": FINGERPRINT}
    print(
        json.dumps(
            {"counts": data["counts"], "scope": data["scope"], "apply": args.apply}, ensure_ascii=False, indent=2
        )
    )
    if not args.apply:
        print("DRY RUN: клуб не создавался, база не изменялась.")
        return
    conn = get_db_connection()
    try:
        club_id = provision(conn, args.create_club, tz) if args.create_club else args.club_id
        save(conn, club_id, data)
        print(
            f"Импорт завершён. Club ID: {club_id}. Обслуживание выключено; рассылки и награды не запускались.",
            flush=True,
        )
        from app.services.guest_pulse import refresh_club

        print("Расчёт пульса по импортированным визитам...", flush=True)
        result = refresh_club(conn, club_id, stage_gizmo_preview=True)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["status"] != "updated":
            raise GizmoError("Данные импортированы, но пульс не пересчитан; запустите rebuild_gizmo_stage_pulse.py")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Avoid traceback/driver output with query arguments containing guest PII.
        print(str(exc) if isinstance(exc, (GizmoError, ValueError)) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
