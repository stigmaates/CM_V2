"""Stage pilot imports: collect first, validate, then one atomic local transaction.

The importer never enables club service, credits balances, or sends messages.
It is deliberately not called by the Langame scheduler.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.integrations import gizmo_normalize as normalize
from app.integrations.gizmo import GizmoError, iter_pages


def all_rows(client, resource, params=None):
    records = []
    ids = set()
    for page in iter_pages(client, resource, params, limit=500):
        for record in page:
            entity = record.get("Model", record)
            identity = entity.get("Id", entity.get("id"))
            if identity is None or str(identity) in ids:
                raise GizmoError(f"{resource}: missing or repeated ID during pagination")
            ids.add(str(identity))
            records.append(record)
        logging.getLogger(__name__).info("Gizmo %s: %s записей", resource, len(records))
        if len(records) > 200000:
            raise GizmoError("Pilot export exceeds 200000 records")
    return records


def closed_session_detail(raw, usage):
    """Guard the same-ID mapping observed on the Next Gizmo 3.0.92 pilot.

    usageSessionId is NOT a usersessions ID on this installation. Equal IDs
    alone are insufficient: require the same guest, exact finite duration and
    a terminal state. Do not guess another join when any check fails.
    """
    session_id = normalize.external_id(raw.get("id"))
    detail = usage.get(session_id)
    if detail is None or normalize.external_id(detail.get("userId")) != normalize.external_id(raw.get("userId")):
        raise GizmoError(f"Session {session_id}: same-ID linkage missing or belongs to a different user")
    try:
        spans = [Decimal(str(record.get("span"))) for record in (raw, detail)]
    except (InvalidOperation, ValueError):
        raise GizmoError(f"Session {session_id}: invalid duration for linkage verification") from None
    if any(not span.is_finite() or span < 0 for span in spans) or spans[0] != spans[1]:
        raise GizmoError(f"Session {session_id}: duration mismatch in same-ID linkage")
    if raw.get("endTime") is None or detail.get("state") not in (2, 17):
        raise GizmoError(f"Session {session_id}: linkage requires a completed session")
    return detail


def collect(client, *, branch_id, start, end, cash_method_ids, include_sessions=True, full_history=False):
    if end.tzinfo is None or (
        not full_history
        and (start is None or start.tzinfo is None or not 0 < (end - start).total_seconds() <= 31 * 86400)
    ):
        raise GizmoError("Pilot period must have a timezone and be at most 31 days")
    branches = all_rows(client, "branches")
    if len(branches) != 1 or int(branches[0]["id"]) != branch_id:
        raise GizmoError("Pilot requires one confirmed branch; shared-network users need a separate mapping")
    methods = all_rows(client, "paymentmethods")
    available_methods = {int(row["id"]) for row in methods}
    if not cash_method_ids or not set(cash_method_ids).issubset(available_methods):
        raise GizmoError("Explicit, existing money payment method IDs are required")
    guests = [normalize.guest(row) for row in all_rows(client, "users", {"IsGuest": "false"})]
    guests = [row for row in guests if row is not None]
    guest_ids = {row["guest_id"] for row in guests}
    hosts = [normalize.host(row) for row in all_rows(client, "hosts", {"BranchId": branch_id})]
    host_ids = {row["external_id"] for row in hosts}
    topup_params = {"BranchId": branch_id}
    if not full_history:
        topup_params.update(DateFrom=start.isoformat(), DateTo=end.isoformat())
    raw_topups = all_rows(client, "deposittransactions", topup_params)
    topups = [
        normalize.topup(row, branch_id=branch_id, cash_method_ids=cash_method_ids, guest_ids=guest_ids)
        for row in raw_topups
    ]
    end_utc = end.astimezone(UTC).replace(tzinfo=None)
    start_utc = None if full_history else start.astimezone(UTC).replace(tzinfo=None)
    topups = [
        row
        for row in topups
        if row is not None and row["topup_at"] < end_utc and (start_utc is None or row["topup_at"] >= start_utc)
    ]
    sessions = {}
    skipped_unlinked = 0
    skipped_open = 0
    skipped_nonmember = 0
    skipped_unknown_host = 0
    if include_sessions:
        # Next 3.0.92 diagnostics: same ID + user + span match;
        # usageSessionId points elsewhere and must not be used as a join.
        # Fetch complete resources: /sessions has no documented date filter.
        usage = {normalize.external_id(row["id"]): row for row in all_rows(client, "usersessions")}
        for raw in all_rows(client, "sessions"):
            if raw.get("startTime") is None:
                skipped_unlinked += 1
                continue
            start_at = normalize.utc_date(raw["startTime"])
            stop_at = normalize.utc_date(raw.get("endTime"), optional=True)
            if start_at >= end.astimezone(UTC).replace(tzinfo=None):
                continue
            if start_utc is not None and stop_at is not None and stop_at < start_utc:
                continue
            user_id = normalize.external_id(raw.get("userId"))
            if user_id not in guest_ids:
                skipped_nonmember += 1
                continue
            if stop_at is None:
                skipped_open += 1
                continue
            detail = usage.get(normalize.external_id(raw["id"]))
            if detail and detail.get("state") not in (2, 17):
                # The session may have ended between the two paginated reads.
                # Re-read that same ID once; all linkage checks still apply.
                detail = client.get(f"usersessions/{normalize.external_id(raw['id'])}")
                if not isinstance(detail, dict) or detail.get("id") != raw["id"]:
                    raise GizmoError("Session detail response has an unexpected identity")
                usage[normalize.external_id(raw["id"])] = detail
            detail = closed_session_detail(raw, usage)
            row = normalize.session(
                dict(raw, hostId=detail["hostId"], state=detail["state"]),
                host_ids=host_ids,
                guest_ids=guest_ids,
            )
            if row:
                sessions[row["id"]] = row
            else:
                skipped_unknown_host += 1
    return {
        "guests": guests,
        "hosts": hosts,
        "topups": topups,
        "sessions": list(sessions.values()),
        "scope": {
            "branch_id": branch_id,
            "start": None if full_history else start.isoformat(),
            "full_history": full_history,
            "end": end.isoformat(),
            "cash_method_ids": sorted(cash_method_ids),
            "sessions_included": include_sessions,
            "session_source": "sessions+usersessions:same-id-user-span:v1",
            "completed_sessions_only": True,
            "event_timezone": "UTC",
        },
        "counts": {
            "guests": len(guests),
            "hosts": len(hosts),
            "topups": len(topups),
            "sessions": len(sessions),
            "sessions_without_start_time": skipped_unlinked,
            "open_sessions_skipped": skipped_open,
            "sessions_unregistered_guest_skipped": skipped_nonmember,
            "sessions_unknown_host_skipped": skipped_unknown_host,
            "deposit_operations_read": len(raw_topups),
        },
    }


def check_target(club):
    if not club or club.get("integration_provider") != "gizmo":
        raise GizmoError("Target must be a Gizmo club")
    if int(club.get("service_enabled", 1)) or int(club.get("integration_ready", 1)):
        raise GizmoError("Pilot import requires disabled service and integration_ready=0")


def save(conn, club_id, data):
    """Idempotent upserts preserve Telegram links and hand-edited PC names/order.

    Use the same advisory lock as the stage mirror. All network I/O is finished
    before acquiring it; any failed write rolls back the entire pilot batch.
    """
    locked = False
    try:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())),0) AS acquired")
            locked = bool((cur.fetchone() or {}).get("acquired"))
            if not locked:
                raise GizmoError("Stage mirror/import is running; retry later")
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clubs WHERE club_id=%s FOR UPDATE", (club_id,))
            check_target(cur.fetchone())
            cur.execute(
                "SELECT external_branch_id, settings FROM club_integrations WHERE club_id=%s FOR UPDATE", (club_id,)
            )
            integration = cur.fetchone()
            if not integration:
                raise GizmoError("Missing club integration configuration")
            branch_id = str(data["scope"]["branch_id"])
            if integration.get("external_branch_id") not in (None, branch_id):
                raise GizmoError("Cannot change the branch of an imported club")
            previous = integration.get("settings")
            previous = json.loads(previous) if isinstance(previous, str) else previous or {}
            for identity in ("source", "session_source"):
                if previous.get(identity) and previous[identity] != data["scope"].get(identity):
                    raise GizmoError("Cannot change an imported club source identity or session ID namespace")
            now = datetime.now(UTC).replace(tzinfo=None)
            for guest in data["guests"]:
                cur.execute(
                    """INSERT INTO guests
                    (club_id,guest_id,phone,fio,birth_date,date_insert,created_at,gender)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE phone=VALUES(phone),fio=VALUES(fio),
                    birth_date=VALUES(birth_date),date_insert=VALUES(date_insert)""",
                    (
                        club_id,
                        guest["guest_id"],
                        guest["phone"],
                        guest["fio"],
                        guest["birth_date"],
                        guest["date_insert"],
                        now,
                        guest["gender"],
                    ),
                )
            # Stage-only surrogate IDs must not collide with new production rows
            # during a later mirror. Business IDs remain the source IDs scoped by club.
            counters = {}

            def surrogate(table, source_column, source_value):
                cur.execute(f"SELECT id FROM {table} WHERE club_id=%s AND {source_column}=%s", (club_id, source_value))
                existing = cur.fetchone()
                if existing:
                    return existing["id"]
                if table not in counters:
                    cur.execute(f"SELECT MIN(id) AS minimum FROM {table}")
                    counters[table] = min(0, int((cur.fetchone() or {}).get("minimum") or 0))
                counters[table] -= 1
                return counters[table]

            for host in data["hosts"]:
                # Source IDs remain stable even after a PC is renamed or retired.
                cur.execute(
                    """INSERT INTO club_pc_names (id,club_id,uuid,display_name,sort_order)
                    VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE uuid=VALUES(uuid)""",
                    (
                        surrogate("club_pc_names", "uuid", host["uuid"]),
                        club_id,
                        host["uuid"],
                        host["display_name"],
                        host["sort_order"],
                    ),
                )
            for row in data["sessions"]:
                cur.execute(
                    """INSERT INTO guest_sessions (club_id,id,guest_id,uuid,date_start,date_stop)
                    VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                    guest_id=VALUES(guest_id),uuid=VALUES(uuid),date_start=VALUES(date_start),date_stop=VALUES(date_stop)""",
                    (club_id, row["id"], row["guest_id"], row["uuid"], row["date_start"], row["date_stop"]),
                )
            for row in data["topups"]:
                cur.execute(
                    """INSERT INTO guest_balance_topups
                    (id,club_id,topup_id,guest_id,amount,topup_at,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                    guest_id=VALUES(guest_id),amount=VALUES(amount),topup_at=VALUES(topup_at),updated_at=VALUES(updated_at)""",
                    (
                        surrogate("guest_balance_topups", "topup_id", row["topup_id"]),
                        club_id,
                        row["topup_id"],
                        row["guest_id"],
                        row["amount"],
                        row["topup_at"],
                        now,
                        now,
                    ),
                )
            cur.execute(
                """UPDATE club_integrations SET external_branch_id=%s, settings=%s,
                last_import_at=%s WHERE club_id=%s""",
                (branch_id, json.dumps(data["scope"]), now, club_id),
            )
            cur.execute(
                """INSERT INTO guest_pulse_dirty (club_id,generation) VALUES (%s,1)
                ON DUPLICATE KEY UPDATE generation=generation+1""",
                (club_id,),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        if locked:
            with conn.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())))")
