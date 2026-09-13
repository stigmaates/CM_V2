"""Read-only team reports. All reporting timestamps are club-local; stored events are UTC."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from app.services.guest_pulse import rows
from app.services.timezones import club_local_datetime_to_utc, get_club_local_now, utc_datetime_to_club_local
from app.services.visits import collapse_sessions_to_visits


def date_range(start, end, today):
    first = date.fromisoformat(start) if start else today.replace(day=1)
    last = date.fromisoformat(end) if end else today
    if first > last or last > today:
        raise ValueError("Укажите даты по порядку, не позднее сегодняшнего дня")
    return first, last


def shift_owner(at, shifts):
    if at is None:
        return None
    matching = [s for s in shifts if s["started_at"] <= at and (s["stopped_at"] is None or at < s["stopped_at"])]
    # Even overlapping shifts of one admin are ambiguous data.
    return matching[0]["admin_id"] if len(matching) == 1 else None


def in_range(at, interval):
    return at is not None and interval[0] <= at.date() <= interval[1]


def build_report(admins, shifts, guests, registrations, sessions, registration_range, cohort_range, now):
    people = {a["admin_id"]: dict(a) for a in admins}
    for shift in shifts:
        people.setdefault(
            shift["admin_id"],
            {
                "admin_id": shift["admin_id"],
                "name": f"Администратор #{shift['admin_id']}",
                "admin_status": "",
                "is_working": False,
                "work_schedule": "",
            },
        )
    people[None] = {
        "admin_id": None,
        "name": "Не определён",
        "admin_status": "",
        "is_working": False,
        "work_schedule": "",
    }
    result = {
        key: {
            **value,
            "club_registrations": 0,
            "club_to_module": 0,
            "module_registrations": 0,
            "module_estimated": 0,
            "shift_count": 0,
            "cohort": 0,
            "visit1": 0,
            "visit2": 0,
            "visit3": 0,
            "has_recent_shift": False,
        }
        for key, value in people.items()
    }
    recent_shift_cutoff = now - timedelta(days=50)
    period_start = datetime.combine(registration_range[0], time.min)
    period_end = datetime.combine(registration_range[1] + timedelta(days=1), time.min)
    for shift in shifts:
        if shift["started_at"] <= now and (
            shift["stopped_at"] is None or shift["stopped_at"] >= recent_shift_cutoff
        ):
            result[shift["admin_id"]]["has_recent_shift"] = True
        if shift["started_at"] < period_end and (
            shift["stopped_at"] is None or shift["stopped_at"] >= period_start
        ):
            result[shift["admin_id"]]["shift_count"] += 1
    grouped = defaultdict(list)
    for session in sessions:
        if session.get("date_stop") and session["date_stop"] <= now:
            grouped[session["guest_id"]].append(session)
    module_guest_ids = {registration["guest_id"] for registration in registrations}
    unknown_club_dates = 0
    for guest in guests:
        at = guest.get("date_insert")
        if at is None:
            unknown_club_dates += 1
        if not (in_range(at, registration_range) or in_range(at, cohort_range)):
            continue
        owner = shift_owner(at, shifts)
        row = result[owner]
        if in_range(at, registration_range):
            row["club_registrations"] += 1
            row["club_to_module"] += guest["guest_id"] in module_guest_ids
        if in_range(at, cohort_range):
            row["cohort"] += 1
            # All completed visits after registration, not just visits inside the date filter.
            visits = collapse_sessions_to_visits([s for s in grouped[guest["guest_id"]] if s["date_start"] >= at])
            for number in (1, 2, 3):
                row[f"visit{number}"] += len(visits) >= number
    unknown_module_dates = 0
    guest_ids = {g["guest_id"] for g in guests}
    for registration in registrations:
        if registration["guest_id"] not in guest_ids:
            continue
        at = registration.get("registered_at")
        if at is None:
            unknown_module_dates += 1
        if in_range(at, registration_range):
            row = result[shift_owner(at, shifts)]
            row["module_registrations"] += 1
            row["module_estimated"] += bool(registration["is_estimated"])
    for row in result.values():
        row["module_conversion"] = (
            round(row["club_to_module"] / row["club_registrations"] * 100, 1)
            if row["club_registrations"]
            else None
        )
        row["conversion12"] = round(row["visit2"] / row["cohort"] * 100, 1) if row["cohort"] else None
        row["conversion23"] = round(row["visit3"] / row["visit2"] * 100, 1) if row["visit2"] else None
    ordered = sorted(result.values(), key=lambda r: (r["admin_id"] is None, -r["club_registrations"], r["name"]))
    return {"admins": ordered, "unknown_club_dates": unknown_club_dates, "unknown_module_dates": unknown_module_dates}


def load_report(conn, club_id, args):
    club = rows(conn, "SELECT timezone FROM clubs WHERE club_id=%s", (club_id,))[0]
    tz = club["timezone"]
    now = get_club_local_now(tz)
    registration_range = date_range(args.get("registration_from"), args.get("registration_to"), now.date())
    cohort_range = date_range(args.get("cohort_from"), args.get("cohort_to"), now.date())
    admins = rows(
        conn,
        """SELECT a.*,COALESCE(s.is_working,1) AS is_working
        FROM team_admins a LEFT JOIN team_admin_settings s
        ON s.club_id=a.club_id AND s.admin_id=a.admin_id
        WHERE a.club_id=%s""",
        (club_id,),
    )
    for admin in admins:
        admin["is_working"] = bool(admin.get("is_working", True))
    shifts = rows(conn, "SELECT * FROM team_shifts WHERE club_id=%s", (club_id,))
    # Match the existing Guest Pulse convention for raw Langame timestamps: UTC -> club time.
    guests = rows(conn, "SELECT guest_id,date_insert FROM guests WHERE club_id=%s", (club_id,))
    registrations = rows(conn, "SELECT * FROM module_registrations WHERE club_id=%s", (club_id,))
    for registration in registrations:
        registration["registered_at"] = utc_datetime_to_club_local(registration["registered_at"], tz)
    cohort_start = club_local_datetime_to_utc(datetime.combine(cohort_range[0], time.min), tz)
    cohort_end = club_local_datetime_to_utc(datetime.combine(cohort_range[1] + timedelta(days=1), time.min), tz)
    sessions = rows(
        conn,
        """SELECT s.guest_id,s.date_start,s.date_stop FROM guest_sessions s
        JOIN guests g ON g.club_id=s.club_id AND g.guest_id=s.guest_id
        WHERE s.club_id=%s AND g.date_insert>=%s AND g.date_insert<%s
        AND s.date_start IS NOT NULL AND s.date_stop IS NOT NULL AND s.date_stop<=%s""",
        (club_id, cohort_start, cohort_end, datetime.now(UTC).replace(tzinfo=None)),
    )
    for items, fields in (
        (shifts, ("started_at", "stopped_at")),
        (guests, ("date_insert",)),
        (sessions, ("date_start", "date_stop")),
    ):
        for item in items:
            for field in fields:
                item[field] = utc_datetime_to_club_local(item.get(field), tz)
    report = build_report(admins, shifts, guests, registrations, sessions, registration_range, cohort_range, now)
    state = (rows(conn, "SELECT * FROM team_sync_state WHERE club_id=%s", (club_id,)) or [{}])[0]
    updated = state.get("updated_at")
    report.update(
        registration_range=[d.isoformat() for d in registration_range],
        cohort_range=[d.isoformat() for d in cohort_range],
        today=now.date().isoformat(),
        timezone=tz,
        updated_at=utc_datetime_to_club_local(updated, tz).isoformat() if updated else None,
        error=state.get("error_code"),
        stale=not updated or datetime.now(UTC).replace(tzinfo=None) - updated > timedelta(hours=1),
    )
    return report


def save_admin_settings(conn, club_id, settings):
    if not isinstance(settings, list) or len(settings) > 1000:
        raise ValueError("Некорректный список администраторов")
    normalized = {}
    for item in settings:
        if not isinstance(item, dict) or not isinstance(item.get("is_working"), bool):
            raise ValueError("Некорректная настройка администратора")
        try:
            admin_id = int(item.get("admin_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Некорректный идентификатор администратора") from exc
        normalized[admin_id] = item["is_working"]

    available = {
        row["admin_id"]
        for row in rows(conn, "SELECT admin_id FROM team_admins WHERE club_id=%s", (club_id,))
    }
    if not set(normalized).issubset(available):
        raise ValueError("Администратор не найден в этом клубе")

    try:
        with conn.cursor() as cursor:
            for admin_id, is_working in normalized.items():
                cursor.execute(
                    """INSERT INTO team_admin_settings
                    (club_id,admin_id,is_working) VALUES(%s,%s,%s)
                    ON DUPLICATE KEY UPDATE is_working=VALUES(is_working)""",
                    (club_id, admin_id, int(is_working)),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
