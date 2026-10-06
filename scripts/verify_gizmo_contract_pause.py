"""Check paused-club contract guards on stage, with all SQL writes forbidden."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import get_db_connection
from app.integrations.gizmo_sync import DIRECTORY, private_json, run_lock
from app.integrations.stage import require_stage_environment
from app.services import game_contracts
from app.services.club_service import ClubServiceDisabled
from scripts.prepare_gizmo_stage_login import CLUB, GUEST, verify_target


class SelectCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def executemany(self, sql, params):
        raise RuntimeError("Batch SQL is forbidden during pause acceptance")

    def execute(self, sql, params=()):
        if not sql.lstrip().upper().startswith("SELECT ") or ";" in sql:
            raise RuntimeError("SQL writes are forbidden during pause acceptance")
        return self.cursor.execute(sql, params)


class SelectConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return SelectCursor(self.conn.cursor())

    def rollback(self):
        self.conn.rollback()

    def commit(self):
        raise RuntimeError("Unexpected commit during paused operation")

    def close(self):
        pass


def run(*, directory=DIRECTORY):
    require_stage_environment()
    with run_lock(directory / "acceptance.lock"), run_lock(directory / f"sync-{CLUB}.lock"):
        conn = get_db_connection()
        try:
            verify_target(conn, directory)
            if private_json(directory / f"sync-{CLUB}.json").get("enabled") is not False:
                raise ValueError("Test sync must be paused")
            with conn.cursor() as cur:
                cur.execute("SELECT service_enabled FROM clubs WHERE club_id=%s", (CLUB,))
                if cur.fetchone()["service_enabled"] != 0:
                    raise ValueError("Test club must remain disabled")
            proxy = SelectConnection(conn)
            checks = {}
            with (
                patch.object(game_contracts, "get_db_connection", lambda: proxy),
                patch.object(game_contracts, "ensure_token_tables", lambda cur: None),
                patch.object(game_contracts, "ensure_cm_bonus_tables", lambda cur: None),
            ):
                operations = {
                    "generate": lambda: game_contracts.generate_weekly_contracts(CLUB, GUEST, "dota2"),
                    "accept": lambda: game_contracts.accept_weekly_contracts(CLUB, GUEST, "dota2", [1, 2, 3]),
                    "refresh": lambda: game_contracts.reroll_guest_contracts(CLUB, GUEST, "dota2"),
                    "repair_reward": lambda: game_contracts.repair_missing_contract_rewards(CLUB, GUEST),
                    "evaluate_reward": lambda: game_contracts.evaluate_contracts_for_guest(CLUB, GUEST, "dota2"),
                    "sync": lambda: game_contracts.sync_contracts_for_guest(CLUB, GUEST, "dota2"),
                }
                for name, operation in operations.items():
                    try:
                        operation()
                    except ClubServiceDisabled:
                        checks[name] = "blocked"
                    else:
                        raise RuntimeError("Paused operation was not blocked: " + name)
            return dict(
                status="complete",
                club_id=CLUB,
                read_only=True,
                checks=checks,
                checked_at_utc=datetime.now(UTC).isoformat(),
                limitation="Paused paths only; concurrent transactions and active Steam API flows not exercised",
            )
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print("Проверка остановлена: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
