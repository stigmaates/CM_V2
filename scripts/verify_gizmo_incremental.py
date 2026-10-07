"""Read-only comparison of incremental Gizmo reads with a full live snapshot.

No application DB connection, credential changes, sends or API writes. Run on
stage with a saved connection. Concurrent source edits can fail comparison;
that is reported rather than silently accepted.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.gizmo import GizmoClient
from app.integrations.gizmo_incremental import collect_sync
from app.integrations.gizmo_onboarding import inspect_connection
from app.integrations.gizmo_sync import DIRECTORY, private_json
from app.integrations.stage import require_stage_environment


class MeasuredClient:
    def __init__(self, client):
        self.client = client
        self.rows = {}
        self.requests = 0

    def get(self, resource, params=None):
        result = self.client.get(resource, params)
        self.requests += 1
        rows = result.get("data") if isinstance(result, dict) else None
        count = len(rows) if isinstance(rows, list) else 1
        self.rows[resource.split("/")[0]] = self.rows.get(resource.split("/")[0], 0) + count
        return result


def compare(before, update, reference):
    result = {}
    for collection, key in (("sessions", "id"), ("topups", "topup_id")):
        merged = {r[key]: r for r in before[collection]}
        merged.update({r[key]: r for r in update[collection]})
        if collection == "sessions":
            for row in update.get("rejected_sessions", []):
                merged.pop(row["id"], None)
        expected = {r[key]: r for r in reference[collection]}
        missing = expected.keys() - merged.keys()
        extra = merged.keys() - expected.keys()
        different = [identity for identity in merged.keys() & expected.keys() if merged[identity] != expected[identity]]
        result[collection] = dict(
            expected=len(expected),
            merged=len(merged),
            missing=len(missing),
            extra=len(extra),
            mismatched=len(different),
        )
    return result


def run(club_id):
    require_stage_environment()
    config = private_json(DIRECTORY / f"sync-{club_id}.json")
    client = GizmoClient(**config["connection"], certificate_pem=config["certificate_pem"], api_key=config["api_key"])
    settings = inspect_connection(client)
    print("Читаем исходную историю для сравнения; база и настройки клуба не меняются.", flush=True)
    first_client = MeasuredClient(client)
    initial = collect_sync(first_client, settings=settings, end=datetime.now(UTC))
    cutoff = datetime.now(UTC)
    print("Проверяем регулярное обновление через реальные фильтры API…", flush=True)
    delta_client = MeasuredClient(client)
    delta = collect_sync(delta_client, settings=initial["scope"], end=cutoff)
    print("Сверяем результат с полной выгрузкой…", flush=True)
    full = collect_sync(client, settings=settings, end=cutoff)
    comparison = compare(initial, delta, full)
    passed = delta["scope"]["sync_mode"] == "incremental" and all(
        not any(row[field] for field in ("missing", "extra", "mismatched")) for row in comparison.values()
    )
    result = dict(
        status="complete" if passed else "needs_review",
        read_only=True,
        club_id=club_id,
        checked_at_utc=datetime.now(UTC).isoformat(),
        sync_mode=delta["scope"]["sync_mode"],
        sync_reason=delta["scope"]["sync_reason"],
        comparison=comparison,
        full_api_rows=first_client.rows,
        incremental_api_rows=delta_client.rows,
        full_api_requests=first_client.requests,
        incremental_api_requests=delta_client.requests,
        pending_sessions=len(delta["scope"]["sync_checkpoint"]["pending"]),
        limitation="Live read-only comparison; concurrent source changes can require a repeat. No DB writes or scheduling tested.",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int, default=900001)
    try:
        passed = run(parser.parse_args().club_id)
    except Exception as exc:
        # Avoid exposing driver parameters, credentials or source records.
        print("Проверка остановлена: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0 if passed else 2)
