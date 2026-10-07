"""Bounded regular reads with atomic DB checkpoints and daily reconciliation.

IDs are used only after validating server-side descending order on every page.
Unfinished sessions survive checkpoints even when older than the overlap. Old
corrections outside the rolling windows are reconciled at least once per day.
"""

from datetime import UTC, datetime, timedelta

from app.integrations.gizmo import GizmoError, GizmoHTTPError, iter_pages, page_rows
from app.integrations.gizmo_import import all_rows, collect
from app.integrations.gizmo_normalize import external_id, utc_date

OVERLAP_IDS = 200
TOPUP_OVERLAP = timedelta(days=7)
RECONCILE_INTERVAL = timedelta(days=1)


class UnsupportedQuery(GizmoError):
    pass


def ordered_tail(client, resource, floor, sort_by, progress=None):
    records = []
    last = None
    try:
        for page in iter_pages(
            client, resource, {"Pagination.SortBy": sort_by, "Pagination.IsAsc": "false"}, limit=500
        ):
            for row in page:
                identity = external_id(row.get("id"))
                if last is not None and identity >= last:
                    raise UnsupportedQuery("Gizmo did not honor descending session order")
                last = identity
                if identity > floor:
                    records.append(row)
            if progress:
                progress(resource, len(records))
            if last is not None and last <= floor:
                break
    except GizmoHTTPError as exc:
        if exc.status == 400:
            raise UnsupportedQuery("Gizmo rejected session sorting") from None
        raise
    return records


def discover_sort(client, rows):
    maximum = max((external_id(r["id"]) for r in rows), default=0)
    for key in ("id", "Id"):
        try:
            page = page_rows(
                client.get("sessions", {"Pagination.SortBy": key, "Pagination.IsAsc": "false", "Pagination.Limit": 20})
            )
        except GizmoHTTPError as exc:
            if exc.status == 400:
                continue
            raise
        ids = [external_id(r.get("id")) for r in page]
        if (not ids and not maximum) or (ids and ids[0] >= maximum and all(a > b for a, b in zip(ids, ids[1:]))):
            return key
    return None


def checkpoint_valid(state, end):
    try:
        if state["version"] != 1 or state["sort_by"] not in ("id", "Id"):
            return False
        if not isinstance(state["session_high_id"], int) or state["session_high_id"] < 0:
            return False
        full_at = datetime.fromisoformat(state["last_full_at"])
        through = datetime.fromisoformat(state["through"])
        return (
            full_at.tzinfo is not None
            and through.tzinfo is not None
            and timedelta(0) <= end - full_at < RECONCILE_INTERVAL
            and timedelta(0) <= end - through < RECONCILE_INTERVAL
            and isinstance(state["pending"], dict)
            and len(state["pending"]) <= 5000
        )
    except (KeyError, TypeError, ValueError):
        return False


class ReadView:
    def __init__(self, client, *, sessions=None, usage=None, topup_start=None, end=None):
        self.client = client
        self.sessions = sessions
        self.usage = usage
        self.topup_start = topup_start
        self.end = end
        self.seen_sessions = []
        self.requests = 0

    def get(self, resource, params=None):
        if resource == "sessions" and self.sessions is not None:
            self.seen_sessions = self.sessions
            return {"data": self.sessions, "nextCursor": None}
        if resource == "usersessions" and self.usage is not None:
            return {"data": self.usage, "nextCursor": None}
        if resource == "deposittransactions" and self.topup_start is not None:
            params = dict(params or {}, DateFrom=self.topup_start.isoformat(), DateTo=self.end.isoformat())
        self.requests += 1
        try:
            result = self.client.get(resource, params)
        except GizmoHTTPError as exc:
            if resource == "deposittransactions" and self.topup_start is not None and exc.status == 400:
                raise UnsupportedQuery("Gizmo rejected deposit date filter") from None
            raise
        if resource == "sessions":
            self.seen_sessions.extend(page_rows(result))
        if resource == "deposittransactions" and self.topup_start is not None:
            for row in page_rows(result):
                if utc_date(row["date"]) < self.topup_start.replace(tzinfo=None):
                    raise UnsupportedQuery("Gizmo did not honor deposit date filter")
        return result


def incremental_view(client, state, end, progress, *, sessions_due=True):
    if not sessions_due:
        start = datetime.fromisoformat(state.get("topups_through", state["through"])).astimezone(UTC) - TOPUP_OVERLAP
        return ReadView(client, sessions=[], usage=[], topup_start=start, end=end)
    floor = max(0, state["session_high_id"] - OVERLAP_IDS)
    recent = ordered_tail(client, "sessions", floor, state["sort_by"], progress)
    sessions = {external_id(row["id"]): row for row in recent}
    # /sessions has no ID-detail endpoint; resolve old open IDs via their user.
    pending = {external_id(key): external_id(user) for key, user in state["pending"].items()}
    users = {user for identity, user in pending.items() if identity not in sessions}
    for user in sorted(users):
        rows = all_rows(client, "sessions", {"UserId": user}, progress=progress)
        if any(external_id(row.get("userId")) != user for row in rows):
            raise UnsupportedQuery("Gizmo did not honor the session user filter")
        for row in rows:
            identity = external_id(row["id"])
            if identity in pending or identity > floor:
                sessions[identity] = row
    usage = {
        external_id(row["id"]): row for row in ordered_tail(client, "usersessions", floor, state["sort_by"], progress)
    }
    for identity, row in sessions.items():
        if row.get("startTime") and row.get("endTime") and identity not in usage:
            if progress:
                progress("session_details", identity)
            detail = client.get(f"usersessions/{identity}")
            if not isinstance(detail, dict) or external_id(detail.get("id")) != identity:
                raise GizmoError("Gizmo session detail identity mismatch")
            usage[identity] = detail
    start = datetime.fromisoformat(state.get("topups_through", state["through"])).astimezone(UTC) - TOPUP_OVERLAP
    return ReadView(client, sessions=list(sessions.values()), usage=list(usage.values()), topup_start=start, end=end)


def make_checkpoint(rows, data, old, end, sort_by, full):
    saved = {row["id"] for row in data["sessions"]}
    pending = {}
    high = 0 if full else old["session_high_id"]
    for row in rows:
        identity = external_id(row["id"])
        high = max(high, identity)
        # Includes open, inconsistent, newly closed during collection, or missing-reference rows.
        # They must not disappear just because a newer ID was seen.
        if identity not in saved:
            pending[str(identity)] = external_id(row.get("userId"))
    return dict(
        version=1,
        session_high_id=high,
        pending=pending,
        through=end.isoformat(),
        last_full_at=end.isoformat() if full else old["last_full_at"],
        sort_by=sort_by,
    )


def collect_sync(client, *, settings, end, force_full=False, progress=None, components=None, references=None):
    parts = set(components) if components is not None else {"guests", "sessions", "topups"}
    if not parts or not parts <= {"guests", "sessions", "topups"}:
        raise GizmoError("Invalid Gizmo update components")
    state = settings.get("sync_checkpoint") or {}
    full = force_full or not checkpoint_valid(state, end)
    reason = "requested" if force_full else "initial_or_daily_reconciliation"
    if not full:
        try:
            view = incremental_view(client, state, end, progress, sessions_due="sessions" in parts)
            context = {}
            if "guests" not in parts:
                if references is None:
                    raise GizmoError("Saved guest and PC references are required for a partial update")
                context = dict(
                    known_guest_ids=references["guests"],
                    known_host_ids=references["hosts"],
                    shared_account_ids=settings.get("shared_account_ids", []),
                )
            data = collect(
                view,
                branch_id=int(settings["branch_id"]),
                start=None,
                end=end,
                cash_method_ids=set(settings["cash_method_ids"]),
                full_history=True,
                progress=progress,
                include_sessions="sessions" in parts,
                include_topups="topups" in parts,
                **context,
            )
        except UnsupportedQuery:
            full = True
            reason = "api_filter_fallback"
    if full:
        parts = {"guests", "sessions", "topups"}
        view = ReadView(client)
        data = collect(
            view,
            branch_id=int(settings["branch_id"]),
            start=None,
            end=end,
            cash_method_ids=set(settings["cash_method_ids"]),
            full_history=True,
            progress=progress,
        )
        sort_by = discover_sort(client, view.seen_sessions)
    else:
        sort_by = state["sort_by"]
        data["scope"].update(full_history=False, start=view.topup_start.isoformat())
    checkpoint = (
        make_checkpoint(view.seen_sessions, data, state, end, sort_by, full)
        if "sessions" in parts
        else dict(state, through=end.isoformat())
    )
    checkpoint["topups_through"] = (
        end.isoformat() if "topups" in parts else state.get("topups_through", state["through"])
    )
    checkpoint["component_success_at"] = dict(state.get("component_success_at") or {})
    checkpoint["component_success_at"].update({part: end.isoformat() for part in parts})
    data["scope"]["sync_checkpoint"] = checkpoint
    data["scope"]["shared_account_ids"] = data["excluded_accounts"]["shared_account_ids"]
    data["scope"]["updated_components"] = sorted(parts)
    data["scope"]["sync_mode"] = "full" if full else "incremental"
    data["scope"]["sync_reason"] = reason if full else "scheduled_update"
    return data
