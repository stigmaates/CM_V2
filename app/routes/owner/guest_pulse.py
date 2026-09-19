from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from flask import abort, jsonify, render_template, request, session, url_for

from app.config import GUEST_PULSE_CONFIG
from app.core import get_db_connection, owner_required
from app.services.guest_pulse import dumps, get_current, loads, rows
from app.services.guest_pulse_filters import parse_filters, score_match, segment_match, select
from app.services.guest_pulse_scores import AUDIENCES, SEGMENTS, overall_score
from app.services.mailing import get_message_variables
from app.services.outbound_policy import outbound_blocked
from app.services.timezones import utc_datetime_to_club_local

from . import owner_bp

PAGE_SIZE = 10


def current_club():
    if not session.get("club_id"):
        abort(403)
    return int(session["club_id"])


def summary(row):
    row["overall"] = overall_score(row)
    result = {
        k: row[k]
        for k in (
            "guest_id",
            "has_telegram",
            "name",
            "lifecycle_status",
            "lifecycle_label",
            "health",
            "value",
            "engagement",
            "overall",
            "audience_type",
        )
    }
    result["phone"] = row.get("phone")
    result["last_visit_date"] = row.get("visits", {}).get("last_visit_date")
    result["segments"] = [label for key, label in SEGMENTS.items() if segment_match(row, key)]
    return result


@owner_bp.get("/guest-pulse")
@owner_required
def guest_pulse():
    current_club()
    return render_template(
        "owner/guest_pulse.html",
        audiences=AUDIENCES,
        segments=SEGMENTS,
        pulse_config=GUEST_PULSE_CONFIG,
        message_variables=get_message_variables(),
        outbound_disabled=outbound_blocked(),
    )


@owner_bp.get("/api/guest-pulse")
@owner_required
def guest_pulse_data():
    cid = current_club()
    try:
        f = parse_filters(request.args)
        page = max(1, int(request.args.get("page", 1)))
        deviation_page = max(1, int(request.args.get("deviation_page", 1)))
        sort_by = request.args.get("sort", "health")
        sort_direction = request.args.get("sort_direction", "asc")
        search = str(request.args.get("search", "")).strip()[:100]
        contact = request.args.get("contact", "all")
        if sort_by not in ("name", "health", "value", "engagement", "overall"):
            raise ValueError("Неизвестная сортировка")
        if sort_direction not in ("asc", "desc"):
            raise ValueError("Неизвестное направление сортировки")
        if contact not in ("all", "with", "without"):
            raise ValueError("Неизвестный фильтр Telegram")
    except (ValueError, TypeError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    conn = get_db_connection()
    try:
        current = get_current(conn, cid)
        state = (
            rows(
                conn,
                """SELECT p.*,c.timezone FROM clubs c LEFT JOIN guest_pulse_clubs p ON p.club_id=c.club_id
            WHERE c.club_id=%s""",
                (cid,),
            )
            or [{}]
        )[0]
    finally:
        conn.close()
    total = Counter(r["audience_type"] for r in current)
    filtered_rows = [r for r in current if score_match(r, f) and segment_match(r, f["segment"])]
    filtered = Counter(r["audience_type"] for r in filtered_rows)
    connected = Counter(r["audience_type"] for r in filtered_rows if r["has_telegram"])
    selected = select(current, f)
    for row in current:
        row["overall"] = overall_score(row)
    audience_summary = list(selected)
    if search:
        needle = search.casefold()
        selected = [
            row
            for row in selected
            if needle in row["name"].casefold()
            or needle in str(row.get("phone") or "").casefold()
            or needle in str(row["guest_id"])
        ]
    if contact == "with":
        selected = [row for row in selected if row["has_telegram"]]
    elif contact == "without":
        selected = [row for row in selected if not row["has_telegram"]]
    deviating = select(current, f, "deviations")
    deviating.sort(key=lambda r: max(d["deviation_ratio"] for d in r["deviations"]), reverse=True)
    def sort_group(group):
        if sort_by == "name":
            return sorted(group, key=lambda r: (r["name"].casefold(), r["guest_id"]), reverse=sort_direction == "desc")
        scored = [r for r in group if r[sort_by]["score"] is not None]
        unscored = [r for r in group if r[sort_by]["score"] is None]
        scored.sort(
            key=lambda r: (r[sort_by]["score"], r["name"].casefold(), r["guest_id"]),
            reverse=sort_direction == "desc",
        )
        return scored + sorted(unscored, key=lambda r: (r["name"].casefold(), r["guest_id"]))

    selected = sort_group([r for r in selected if r["has_telegram"]]) + sort_group(
        [r for r in selected if not r["has_telegram"]]
    )
    scored_selected = [r["overall"]["score"] for r in selected if r["overall"]["score"] is not None]
    audience_scored = [r["overall"]["score"] for r in audience_summary if r["overall"]["score"] is not None]
    at = utc_datetime_to_club_local(state.get("calculated_at"), state.get("timezone"))
    return jsonify(
        ok=True,
        filters=f,
        total=sum(filtered.values()),
        selected_count=len(selected),
        selected_telegram_count=sum(r["has_telegram"] for r in selected),
        selected_without_telegram_count=sum(not r["has_telegram"] for r in selected),
        selected_average_score=round(sum(scored_selected) / len(scored_selected), 1) if scored_selected else None,
        audience_summary_count=len(audience_summary),
        audience_summary_telegram_count=sum(r["has_telegram"] for r in audience_summary),
        audience_summary_without_telegram_count=sum(not r["has_telegram"] for r in audience_summary),
        audience_summary_average_score=(
            round(sum(audience_scored) / len(audience_scored), 1) if audience_scored else None
        ),
        audiences=[
            dict(
                key=k,
                label=label,
                color=c,
                count=filtered[k],
                total=total[k],
                telegram_count=connected[k],
                without_telegram_count=filtered[k] - connected[k],
            )
            for k, label, c in AUDIENCES
        ],
        guests=[summary(r) for r in selected[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]],
        page=page,
        page_size=PAGE_SIZE,
        sort=sort_by,
        sort_direction=sort_direction,
        deviations=[
            {**summary(r), "deviations": r["deviations"]}
            for r in deviating[(deviation_page - 1) * PAGE_SIZE : deviation_page * PAGE_SIZE]
        ],
        deviation_count=len(deviating),
        deviation_telegram_count=sum(r["has_telegram"] for r in deviating),
        deviation_page=deviation_page,
        calculated_at=at.isoformat() if at else None,
        timezone=state.get("timezone"),
        stale=not state.get("calculated_at")
        or datetime.now(UTC).replace(tzinfo=None) - state["calculated_at"] > timedelta(hours=26),
    )


@owner_bp.get("/api/guest-pulse/guests/<int:guest_id>")
@owner_required
def guest_pulse_guest(guest_id):
    cid = current_club()
    conn = get_db_connection()
    try:
        result = rows(
            conn,
            """SELECT p.detail_json,g.telegram_id,
                   up.favorite_game,up.favorite_game_hours,
                   up.recent_game_14d,up.recent_game_14d_hours,
                   up.steam_game_stats_updated_at
            FROM guest_pulse_current p
            JOIN guests g ON g.club_id=p.club_id AND g.guest_id=p.guest_id
            LEFT JOIN user_portrait up ON up.club_id=p.club_id AND up.guest_id=p.guest_id
            WHERE p.club_id=%s AND p.guest_id=%s""",
            (cid, guest_id),
        )
        if not result:
            abort(404)
        row = loads(result[0]["detail_json"])
        row["overall"] = overall_score(row)
        row["has_telegram"] = bool(result[0]["telegram_id"])
        row["games"] = {
            "favorite_game": result[0].get("favorite_game"),
            "favorite_game_hours": (
                float(result[0]["favorite_game_hours"]) if result[0].get("favorite_game_hours") is not None else None
            ),
            "recent_game_14d": result[0].get("recent_game_14d"),
            "recent_game_14d_hours": (
                float(result[0]["recent_game_14d_hours"])
                if result[0].get("recent_game_14d_hours") is not None
                else None
            ),
            "updated_at": (
                result[0]["steam_game_stats_updated_at"].isoformat()
                if result[0].get("steam_game_stats_updated_at")
                else None
            ),
        }
        history = rows(
            conn,
            """SELECT snapshot_date,health_score,value_score,engagement_score,reconstructed
            FROM guest_score_history WHERE club_id=%s AND guest_id=%s ORDER BY snapshot_date DESC LIMIT 31""",
            (cid, guest_id),
        )
        for h in history:
            h["snapshot_date"] = h["snapshot_date"].isoformat()
            for key in ("health_score", "value_score", "engagement_score"):
                h[key] = float(h[key]) if h[key] is not None else None
        events = rows(
            conn,
            """SELECT from_status,to_status,changed_at,reason_code,reconstructed FROM guest_lifecycle_events
            WHERE club_id=%s AND guest_id=%s ORDER BY changed_at DESC LIMIT 30""",
            (cid, guest_id),
        )
        tz = (rows(conn, "SELECT timezone FROM clubs WHERE club_id=%s", (cid,)) or [{}])[0].get("timezone")
        for e in events:
            e["changed_at"] = utc_datetime_to_club_local(e["changed_at"], tz).isoformat()
        return jsonify(ok=True, guest=row, history=history, events=events)
    finally:
        conn.close()


@owner_bp.post("/api/guest-pulse/selection")
@owner_required
def guest_pulse_selection():
    cid = current_club()
    body = request.get_json() or {}
    try:
        if not isinstance(body, dict):
            raise ValueError("Некорректная выборка")
        raw_filters = body.get("filters", {})
        f = parse_filters(raw_filters)
        search = str(raw_filters.get("search", "")).strip()[:100]
        contact = raw_filters.get("contact", "all")
        if contact not in ("all", "with", "without"):
            raise ValueError("Неизвестный фильтр Telegram")
        mode = body.get("mode", "audience")
        if mode not in ("audience", "deviations", "guest"):
            raise ValueError("Неизвестная выборка")
        gid = int(body.get("guest_id") or 0)
    except (ValueError, TypeError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    conn = get_db_connection()
    try:
        current = get_current(conn, cid)
        selected = [r for r in current if r["guest_id"] == gid] if mode == "guest" else select(current, f, mode)
        if mode == "audience" and search:
            needle = search.casefold()
            selected = [
                row
                for row in selected
                if needle in row["name"].casefold()
                or needle in str(row.get("phone") or "").casefold()
                or needle in str(row["guest_id"])
            ]
        if mode == "audience" and contact == "without":
            selected = []
        selected = [r for r in selected if r["has_telegram"]]
        if not selected:
            return jsonify(ok=False, error="В выбранной аудитории нет гостей с Telegram"), 400
        key = uuid4().hex
        now = datetime.now(UTC).replace(tzinfo=None)
        payload = {"filters": f, "mode": mode, "guest_ids": [r["guest_id"] for r in selected]}
        with conn.cursor() as cur:
            cur.execute("DELETE FROM guest_pulse_selections WHERE expires_at<%s", (now,))
            cur.execute(
                """INSERT INTO guest_pulse_selections (id,club_id,user_id,selection_json,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (key, cid, int(session["user_id"]), dumps(payload), now, now + timedelta(hours=2)),
            )
        conn.commit()
        group = selection_group(conn, key)
    finally:
        conn.close()
    return jsonify(ok=True, count=len(selected), group=group, url=url_for("owner.guest_pulse"))


def load_selection(conn, key, *, lock=False):
    if not isinstance(key, str) or len(key) != 32:
        abort(404)
    result = rows(
        conn,
        """SELECT * FROM guest_pulse_selections WHERE id=%s AND club_id=%s AND user_id=%s
        AND expires_at>%s""" + (" FOR UPDATE" if lock else ""),
        (key, current_club(), int(session["user_id"]), datetime.now(UTC).replace(tzinfo=None)),
    )
    if not result:
        abort(404)
    row = result[0]
    row["selection"] = loads(row["selection_json"])
    return row


def selection_group(conn, key):
    selection = load_selection(conn, key)["selection"]
    ids = set(selection["guest_ids"])
    current = {r["guest_id"]: r for r in get_current(conn, current_club())}
    placeholders = ",".join(["%s"] * len(ids))
    guests = (
        rows(
            conn,
            f"SELECT guest_id,fio,phone,telegram_id FROM guests WHERE club_id=%s AND guest_id IN ({placeholders})",
            (current_club(), *sorted(ids)),
        )
        if ids
        else []
    )
    guests = [r for r in guests if r["telegram_id"]]
    return {
        "key": key,
        "source": "guest_pulse",
        "selection_id": key,
        "old_label": "Пульс гостя",
        "new_label": "Выбранная аудитория · с Telegram",
        "total_count": len(guests),
        "guest_ids": [r["guest_id"] for r in guests],
        "guests": [
            {
                "guest_id": r["guest_id"],
                "fio": r["fio"],
                "phone": r["phone"],
                "has_telegram": bool(r["telegram_id"]),
                "visits_30d": current.get(r["guest_id"], {}).get("visits", {}).get("visits_30d", 0),
            }
            for r in guests
        ],
    }
