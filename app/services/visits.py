"""Shared completed-visit normalization (a gap of up to two hours is one visit)."""

from datetime import timedelta


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
