"""Read-only evidence about session relationships; never chooses a fallback join."""

from collections import Counter
from datetime import UTC, datetime

from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_import import all_rows

SESSION_FIELDS = ("id", "userId", "usageSessionId", "isFirstUsageSession", "startTime", "endTime", "span")
USAGE_FIELDS = ("id", "userId", "hostId", "state", "span")


def identifiers(row, fields):
    return {key: row.get(key) for key in fields}


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise GizmoError("Session timestamp without timezone")
    return parsed.astimezone(UTC)


def describe_links(sessions, usage_rows, start, end):
    usage = {str(row["id"]): row for row in usage_rows}
    counts = Counter()
    examples = {}
    for row in sessions:
        if row.get("startTime") is None:
            counts["no_start_time_all_history"] += 1
            continue
        if timestamp(row["startTime"]) >= end:
            continue
        if row.get("endTime") is not None and timestamp(row["endTime"]) < start:
            continue
        counts["accounting_sessions_in_period"] += 1
        target = usage.get(str(row.get("usageSessionId")))
        same_id = usage.get(str(row["id"]))
        if row.get("usageSessionId") is None:
            reason = "no_usage_reference"
        elif target is None:
            reason = "reference_not_in_list"
        elif str(target.get("userId")) != str(row.get("userId")):
            reason = "different_user"
        else:
            reason = "reference_matches_user"
        counts[reason] += 1
        if same_id and str(same_id.get("userId")) == str(row.get("userId")):
            counts["same_id_matches_user_not_a_verified_relation"] += 1
        if reason not in examples:
            examples[reason] = []
        if len(examples[reason]) < 5:
            examples[reason].append(
                {
                    "session": identifiers(row, SESSION_FIELDS),
                    "referenced_usage": identifiers(target, USAGE_FIELDS) if target else None,
                    "same_id_candidate_unverified": identifiers(same_id, USAGE_FIELDS) if same_id else None,
                }
            )
    return {
        "counts": dict(counts),
        "examples": examples,
        "total_accounting_sessions": len(sessions),
        "total_usage_sessions": len(usage_rows),
    }


def diagnose(client, start, end):
    usage = all_rows(client, "usersessions")
    sessions = all_rows(client, "sessions")
    result = describe_links(sessions, usage, start, end)
    checks = []
    for reason in ("reference_not_in_list", "different_user"):
        for example in result["examples"].get(reason, [])[:3]:
            reference = example["session"]["usageSessionId"]
            if not str(reference).isdigit():
                continue
            check = {"requested_usage_id": reference}
            try:
                detail = client.get(f"usersessions/{reference}")
                check["result"] = (
                    identifiers(detail, USAGE_FIELDS)
                    if isinstance(detail, dict)
                    else {"unexpected_type": type(detail).__name__}
                )
            except GizmoError as exc:
                check["error"] = str(exc)
            checks.append(check)
    result["direct_lookups"] = checks
    result["read_only"] = True
    result["period"] = {"start": start.isoformat(), "end": end.isoformat()}
    return result
