"""Shared completed-session and visit normalization."""

from datetime import timedelta


MAX_REPORT_SESSION_HOURS = 24


def clip_completed_session_to_range(
    row,
    range_start,
    range_end,
    *,
    max_hours=MAX_REPORT_SESSION_HOURS,
):
    """Clip a trustworthy completed session to a report range.

    Langame can leave stale sessions without ``date_stop``. Treating those as
    active until the end of a report makes one PC look occupied for the whole
    selected period. Very long completed rows are rejected for the same reason.
    """
    session_start = row.get("date_start")
    session_end = row.get("date_stop")
    if not session_start or not session_end or session_end <= session_start:
        return None
    if session_end - session_start > timedelta(hours=max_hours):
        return None

    clipped_start = max(session_start, range_start)
    clipped_end = min(session_end, range_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def collapse_sessions_to_visits(rows, gap_hours=2):
    valid = [r for r in rows if r.get("date_start") and r.get("date_stop") and r["date_stop"] > r["date_start"]]
    visits = []
    for row in sorted(valid, key=lambda r: r["date_start"]):
        start, stop = row["date_start"], row["date_stop"]
        if not visits or start > visits[-1]["date_stop"] + timedelta(hours=gap_hours):
            visits.append(
                {"date_start": start, "date_stop": stop, "played_hours": (stop - start).total_seconds() / 3600}
            )
        else:
            visit = visits[-1]
            # Sum the union of sessions: neither overlaps nor breaks are playing time.
            visit["played_hours"] += max(0, (stop - max(start, visit["date_stop"])).total_seconds() / 3600)
            visit["date_stop"] = max(stop, visit["date_stop"])
    return visits
