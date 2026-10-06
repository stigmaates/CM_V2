"""Stage pilot imports: collect first, validate, then one atomic local transaction.

The importer never enables club service, credits balances, or sends messages.
It is deliberately not called by the Langame scheduler.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.integrations import gizmo_normalize as normalize
from app.integrations.gizmo import GizmoError, GizmoHTTPError, iter_pages


def referenced_record(client, resource, identity):
    """Resolve history omitted from list endpoints; never fabricate its owner."""
    try:
        row = client.get(f"{resource}/{identity}")
    except GizmoHTTPError as exc:
        if exc.status == 404:
            return None
        raise
    _, model = normalize.payload(row, (0, 1))
    if normalize.external_id(model.get("Id")) != identity:
        raise GizmoError(f"{resource}/{identity}: detail response has an unexpected identity")
    return row


def all_rows(client, resource, params=None, *, progress=None):
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
        if progress:
            progress(resource, len(records))
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


def collect(
    client, *, branch_id, start, end, cash_method_ids, include_sessions=True, full_history=False, progress=None
):
    if end.tzinfo is None or (
        not full_history
        and (start is None or start.tzinfo is None or not 0 < (end - start).total_seconds() <= 31 * 86400)
    ):
        raise GizmoError("Pilot period must have a timezone and be at most 31 days")

    def read(resource, params=None):
        return all_rows(client, resource, params, progress=progress)

    branches = read("branches")
    if len(branches) != 1 or int(branches[0]["id"]) != branch_id:
        raise GizmoError("Pilot requires one confirmed branch; shared-network users need a separate mapping")
    methods = read("paymentmethods")
    available_methods = {int(row["id"]) for row in methods}
    if not cash_method_ids or not set(cash_method_ids).issubset(available_methods):
        raise GizmoError("Explicit, existing money payment method IDs are required")
    raw_guests = read("users", {"IsGuest": "false"})
    guests = [normalize.guest(row) for row in raw_guests]
    guests = [row for row in guests if row is not None]
    guest_ids = {row["guest_id"] for row in guests}
    hosts = [normalize.host(row) for row in read("hosts", {"BranchId": branch_id})]
    host_ids = {row["external_id"] for row in hosts}
    topup_params = {"BranchId": branch_id}
    if not full_history:
        topup_params.update(DateFrom=start.isoformat(), DateTo=end.isoformat())
    raw_topups = read("deposittransactions", topup_params)
    raw_sessions = read("sessions") if include_sessions else []
    # The live list can omit both guest accounts and deleted members. Resolve
    # referenced IDs once before normalizing payments or personal visits.
    shared_accounts = {normalize.external_id(row["Model"]["Id"]) for row in raw_guests if row["Type"] == 1}
    referenced_users = {
        normalize.external_id(row.get("userId")) for row in raw_sessions if row.get("startTime") is not None
    }
    referenced_users.update(
        normalize.external_id(row.get("userId"))
        for row in raw_topups
        if row.get("type") == 0
        and row.get("isVoid") is False
        and row.get("branchId") == branch_id
        and row.get("paymentMethodId") in cash_method_ids
    )
    missing_accounts = set()
    for user_id in sorted(referenced_users - guest_ids - shared_accounts):
        raw_user = referenced_record(client, "users", user_id)
        if raw_user is None:
            missing_accounts.add(user_id)
        elif raw_user["Type"] == 1:
            shared_accounts.add(user_id)
        else:
            guests.append(normalize.guest(raw_user))
            guest_ids.add(user_id)
    topups = [
        normalize.topup(
            row, branch_id=branch_id, cash_method_ids=cash_method_ids, guest_ids=guest_ids | shared_accounts
        )
        for row in raw_topups
    ]
    end_utc = end.astimezone(UTC).replace(tzinfo=None)
    start_utc = None if full_history else start.astimezone(UTC).replace(tzinfo=None)
    topups = [
        row
        for row in topups
        if row is not None and row["topup_at"] < end_utc and (start_utc is None or row["topup_at"] >= start_utc)
    ]
    for row in topups:
        if row["guest_id"] in shared_accounts:
            row["source_guest_id"], row["guest_id"] = row["guest_id"], None
    sessions = {}
    skipped_unlinked = 0
    skipped_open = 0
    skipped_nonmember = 0
    skipped_unknown_host = 0
    rejected_sessions = []
    missing_hosts = set()
    shared_sessions = 0
    if include_sessions:
        # Next 3.0.92 diagnostics: same ID + user + span match;
        # usageSessionId points elsewhere and must not be used as a join.
        # Fetch complete resources: /sessions has no documented date filter.
        usage = {normalize.external_id(row["id"]): row for row in read("usersessions")}
        for raw in raw_sessions:
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
            if user_id not in guest_ids | shared_accounts:
                skipped_nonmember += 1
                continue
            if stop_at is None:
                skipped_open += 1
                continue
            if stop_at <= start_at:
                # Zero/negative wall-clock intervals cannot represent an analytical
                # visit. Quarantine explicitly; keep strict linkage for valid rows.
                rejected_sessions.append(
                    {
                        "id": normalize.external_id(raw["id"]),
                        "reason": "end_equals_start" if stop_at == start_at else "end_before_start",
                        "start_utc": start_at.isoformat(),
                        "end_utc": stop_at.isoformat(),
                    }
                )
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
            host_id = normalize.external_id(detail.get("hostId"))
            if host_id not in host_ids and host_id not in missing_hosts:
                raw_host = referenced_record(client, "hosts", host_id)
                if raw_host is None:
                    missing_hosts.add(host_id)
                else:
                    hosts.append(normalize.host(raw_host))
                    host_ids.add(host_id)
            row = normalize.session(
                dict(raw, hostId=detail["hostId"], state=detail["state"], userIsGuest=False),
                host_ids=host_ids,
                guest_ids=guest_ids | shared_accounts,
            )
            if row:
                if user_id in shared_accounts:
                    row["source_guest_id"], row["guest_id"] = user_id, None
                    shared_sessions += 1
                sessions[row["id"]] = row
            else:
                skipped_unknown_host += 1
    if rejected_sessions:
        logging.getLogger(__name__).warning(
            "Gizmo: исключено сессий с окончанием не позже начала: %s; примеры ID: %s",
            len(rejected_sessions),
            ", ".join(str(row["id"]) for row in rejected_sessions[:10]),
        )
    shared_topups = [row for row in topups if row["guest_id"] is None]
    return {
        "rejected_sessions": rejected_sessions,
        "guests": guests,
        "hosts": hosts,
        "topups": topups,
        "sessions": list(sessions.values()),
        "excluded_accounts": {
            "shared_account_ids": sorted(shared_accounts),
            "missing_account_ids": sorted(missing_accounts),
            "missing_host_ids": sorted(missing_hosts),
        },
        "nonpersonal_activity": {
            "sessions": shared_sessions,
            "topups": len(shared_topups),
            "topup_amount": str(sum((row["amount"] for row in shared_topups), Decimal(0))),
        },
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
            "active_hosts": sum(not row["deleted"] for row in hosts),
            "archived_hosts": sum(row["deleted"] for row in hosts),
            "topups": len(topups),
            "sessions": len(sessions),
            "sessions_without_start_time": skipped_unlinked,
            "open_sessions_skipped": skipped_open,
            "sessions_unregistered_guest_skipped": skipped_nonmember,
            "sessions_shared_account_imported": shared_sessions,
            "personal_sessions": len(sessions) - shared_sessions,
            "personal_topups": len(topups) - len(shared_topups),
            "sessions_unknown_host_skipped": skipped_unknown_host,
            "sessions_invalid_time_skipped": len(rejected_sessions),
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

            def write_batches(label, statement, values):
                # PyMySQL emits a multi-value INSERT per batch, avoiding one
                # round trip per record. Commit remains atomic for the whole run.
                total = len(values)
                for offset in range(0, total, 500):
                    cur.executemany(statement, values[offset : offset + 500])
                    logging.getLogger(__name__).info(
                        "Gizmo запись %s: %s/%s (до общего commit)",
                        label,
                        min(offset + 500, total),
                        total,
                    )

            write_batches(
                "гостей",
                """INSERT INTO guests
                (club_id,guest_id,phone,fio,birth_date,date_insert,created_at,gender)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE phone=VALUES(phone),fio=VALUES(fio),
                birth_date=VALUES(birth_date),date_insert=VALUES(date_insert)""",
                [
                    (club_id, g["guest_id"], g["phone"], g["fio"], g["birth_date"], g["date_insert"], now, g["gender"])
                    for g in data["guests"]
                ],
            )
            # Cache existing source IDs once, under the stage mirror lock.
            # Negative surrogate IDs do not collide with future production rows.
            counters, existing_ids = {}, {}

            def surrogate(table, source_column, source_value):
                if table not in existing_ids:
                    cur.execute(f"SELECT id,{source_column} FROM {table} WHERE club_id=%s", (club_id,))
                    existing_ids[table] = {str(row[source_column]): row["id"] for row in cur.fetchall()}
                key = str(source_value)
                if key in existing_ids[table]:
                    return existing_ids[table][key]
                if table not in counters:
                    cur.execute(f"SELECT MIN(id) AS minimum FROM {table}")
                    counters[table] = min(0, int((cur.fetchone() or {}).get("minimum") or 0))
                counters[table] -= 1
                existing_ids[table][key] = counters[table]
                return counters[table]

            write_batches(
                "ПК",
                """INSERT INTO club_pc_names (id,club_id,uuid,display_name,sort_order,is_archived)
                VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE is_archived=VALUES(is_archived)""",
                [
                    (
                        surrogate("club_pc_names", "uuid", h["uuid"]),
                        club_id,
                        h["uuid"],
                        h["display_name"],
                        h["sort_order"],
                        int(h.get("deleted", False)),
                    )
                    for h in data["hosts"]
                ],
            )
            # Remove only rejected source IDs from this club, in the same transaction.
            rejected = data.get("rejected_sessions", [])
            for offset in range(0, len(rejected), 500):
                ids = [row["id"] for row in rejected[offset : offset + 500]]
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(f"DELETE FROM guest_sessions WHERE club_id=%s AND id IN ({placeholders})", (club_id, *ids))
            write_batches(
                "сессий",
                """INSERT INTO guest_sessions (club_id,id,guest_id,uuid,date_start,date_stop,source_guest_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                guest_id=VALUES(guest_id),uuid=VALUES(uuid),date_start=VALUES(date_start),date_stop=VALUES(date_stop),
                source_guest_id=VALUES(source_guest_id)""",
                [
                    (
                        club_id,
                        r["id"],
                        r["guest_id"],
                        r["uuid"],
                        r["date_start"],
                        r["date_stop"],
                        r.get("source_guest_id", r["guest_id"]),
                    )
                    for r in data["sessions"]
                ],
            )
            write_batches(
                "пополнений",
                """INSERT INTO guest_balance_topups
                (id,club_id,topup_id,guest_id,amount,topup_at,created_at,updated_at,source_guest_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                guest_id=VALUES(guest_id),amount=VALUES(amount),topup_at=VALUES(topup_at),updated_at=VALUES(updated_at),
                source_guest_id=VALUES(source_guest_id)""",
                [
                    (
                        surrogate("guest_balance_topups", "topup_id", r["topup_id"]),
                        club_id,
                        r["topup_id"],
                        r["guest_id"],
                        r["amount"],
                        r["topup_at"],
                        now,
                        now,
                        r.get("source_guest_id", r["guest_id"]),
                    )
                    for r in data["topups"]
                ],
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
