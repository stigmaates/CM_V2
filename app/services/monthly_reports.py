"""Monthly club report calculations.

All timestamps passed to the pure builder are club-local. Database loading is kept
separate so the same result can feed the admin preview, PDF and future exports.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from app.config import BALANCE_TOPUP_MAX_AMOUNT, GUEST_PULSE_CONFIG, MONTHLY_REPORT_ATTRIBUTION_DAYS
from app.services.timezones import club_local_datetime_to_utc, get_club_local_now, utc_datetime_to_club_local
from app.services.visits import collapse_sessions_to_visits

REPORT_VERSION = "v1"
MONTHS_RU = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
PULSE_LABELS = {
    "new": "Новые / формируют привычку",
    "churned": "Потерянные",
    "valuable_risk": "Ценные в зоне риска",
    "low_engagement": "Активные, но не вовлечены",
    "loyal": "Лояльное ядро",
    "risk": "В зоне риска",
    "other": "Остальные",
}


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if year < 2020 or year > 2100 or month not in range(1, 13):
        raise ValueError("Некорректный месяц отчёта")
    start = datetime(year, month, 1)
    return start, (datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1))


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _in_period(value: datetime | None, start: datetime, end: datetime) -> bool:
    return bool(value and start <= value < end)


def _percent(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def _change(current: float, previous: float) -> dict[str, float | None]:
    return {
        "absolute": round(current - previous, 2),
        "percent": round((current / previous - 1) * 100, 1) if previous else None,
    }


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _group_visits(sessions: Iterable[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sessions:
        if row.get("guest_id") is not None:
            grouped[int(row["guest_id"])].append(row)
    return {guest_id: collapse_sessions_to_visits(rows) for guest_id, rows in grouped.items()}


def _period_visit_counts(
    visits_by_guest: dict[int, list[dict[str, Any]]], start: datetime, end: datetime
) -> dict[int, int]:
    return {
        guest_id: sum(_in_period(visit["date_start"], start, end) for visit in visits)
        for guest_id, visits in visits_by_guest.items()
    }


def _snapshot_state(rows: Iterable[dict[str, Any]], cutoff: date) -> dict[int, dict[str, Any]]:
    state: dict[int, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: item["snapshot_date"]):
        if row["snapshot_date"] > cutoff:
            continue
        detail = _json(row.get("detail_json"))
        state[int(row["guest_id"])] = {
            **row,
            "audience_type": detail.get("audience_type") or _audience_from_lifecycle(row.get("lifecycle_status")),
        }
    return state


def _audience_from_lifecycle(status: str | None) -> str:
    if status in {"NEW", "ACTIVATING"}:
        return "new"
    if status == "CHURNED":
        return "churned"
    if status in {"HIGH_RISK", "AT_RISK"}:
        return "risk"
    return "other"


def _health_distribution(state: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    thresholds = GUEST_PULSE_CONFIG
    groups = [
        ("healthy", "Healthy", lambda score: score >= thresholds["healthy_min"]),
        ("stable", "Stable", lambda score: thresholds["stable_min"] <= score < thresholds["healthy_min"]),
        ("risk", "Risk", lambda score: thresholds["at_risk_min"] <= score < thresholds["stable_min"]),
        ("critical", "Critical", lambda score: score < thresholds["at_risk_min"]),
    ]
    scores = [float(row["health_score"]) for row in state.values() if row.get("health_score") is not None]
    return [
        {
            "code": code,
            "label": label,
            "count": sum(check(score) for score in scores),
            "percent": _percent(sum(check(score) for score in scores), len(scores)),
        }
        for code, label, check in groups
    ]


def _mechanic_stats(rows: Iterable[dict[str, Any]], unique_guests: int) -> dict[str, Any]:
    counts = Counter(int(row["guest_id"]) for row in rows if row.get("guest_id") is not None)
    participants = len(counts)
    return {
        "participants": participants,
        "actions": sum(counts.values()),
        "repeat_participants": sum(count > 1 for count in counts.values()),
        "average_actions": round(sum(counts.values()) / participants, 2) if participants else None,
        "engagement_percent": _percent(participants, unique_guests),
        "guest_ids": sorted(counts),
    }


def _campaigns(
    recipients: Iterable[dict[str, Any]],
    visits_by_guest: dict[int, list[dict[str, Any]]],
    topups: Iterable[dict[str, Any]],
    period_end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topups_by_guest: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in topups:
        topups_by_guest[int(row["guest_id"])].append(row)
    grouped: dict[tuple[str, str | int], dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    meta: dict[tuple[str, str | int], dict[str, Any]] = {}
    for row in recipients:
        filters = _json(row.get("filters_json"))
        automation = filters.get("auto_mailing")
        campaign_type = "auto" if automation else "manual"
        key = (campaign_type, str(automation) if automation else int(row["mailing_id"]))
        meta[key] = {
            "type": campaign_type,
            "code": automation,
            "title": row.get("scenario_title")
            or (f"Рассылка #{row['mailing_id']}" if not automation else str(automation)),
            "audience": filters.get("segment_name") or filters.get("audience") or "Выбранная аудитория",
        }
        guest_id = row.get("guest_id")
        interaction_at = row.get("interaction_at")
        if guest_id is None or interaction_at is None:
            continue
        guest_id = int(guest_id)
        grouped[key][guest_id].append({**row, "guest_id": guest_id})

    output = []
    window = timedelta(days=MONTHLY_REPORT_ATTRIBUTION_DAYS)
    for key, guests in grouped.items():
        sent_rows = [
            min((row for row in rows if row.get("status") == "sent"), key=lambda row: row["interaction_at"])
            for rows in guests.values()
            if any(row.get("status") == "sent" for row in rows)
        ]
        returned = 0
        topup_amount = 0.0
        return_details = []
        for row in sent_rows:
            at = row["interaction_at"]
            deadline = min(at + window, period_end)
            next_visit = next(
                (visit for visit in visits_by_guest.get(row["guest_id"], []) if at < visit["date_start"] < deadline),
                None,
            )
            if next_visit:
                returned += 1
                amount = sum(
                    float(topup.get("amount") or 0)
                    for topup in topups_by_guest.get(row["guest_id"], [])
                    if next_visit["date_start"] <= topup["topup_at"] < period_end
                )
                topup_amount += amount
                return_details.append(
                    {"guest_id": row["guest_id"], "visit_at": next_visit["date_start"], "topups": amount}
                )
        item = {
            **meta[key],
            "targeted": len(guests),
            "sent": len(sent_rows),
            "returned": returned,
            "conversion_percent": _percent(returned, len(sent_rows)),
            "topup_amount": round(topup_amount, 2),
            "return_details": return_details,
        }
        output.append(item)
    auto = sorted((row for row in output if row["type"] == "auto"), key=lambda row: (-row["sent"], row["title"]))
    manual = sorted(
        (row for row in output if row["type"] == "manual"),
        key=lambda row: (-(row["conversion_percent"] or 0), -row["returned"], -row["sent"]),
    )
    return auto, manual


def build_report_from_sources(
    sources: dict[str, list[dict[str, Any]]],
    club: dict[str, Any],
    year: int,
    month: int,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    start, end = month_bounds(year, month)
    prev_year, prev_month_number = previous_month(year, month)
    prev_start, _ = month_bounds(prev_year, prev_month_number)
    generated_at = generated_at or datetime.now()

    visits_by_guest = _group_visits(sources.get("sessions", []))
    current_counts = _period_visit_counts(visits_by_guest, start, end)
    previous_counts = _period_visit_counts(visits_by_guest, prev_start, start)
    active = {guest_id for guest_id, count in current_counts.items() if count}
    previous_active = {guest_id for guest_id, count in previous_counts.items() if count}
    first_visit = {guest_id: visits[0]["date_start"] for guest_id, visits in visits_by_guest.items() if visits}
    new_guests = {guest_id for guest_id, at in first_visit.items() if _in_period(at, start, end)}
    previous_new = {guest_id for guest_id, at in first_visit.items() if _in_period(at, prev_start, start)}

    module_rows = sources.get("module_registrations", [])
    new_module = [row for row in module_rows if _in_period(row.get("registered_at"), start, end)]
    previous_module = [row for row in module_rows if _in_period(row.get("registered_at"), prev_start, start)]
    lifecycle = sources.get("lifecycle_events", [])
    reactivated = {
        int(row["guest_id"])
        for row in lifecycle
        if row.get("to_status") == "REACTIVATED" and _in_period(row.get("changed_at"), start, end)
    }
    lost = {
        int(row["guest_id"])
        for row in lifecycle
        if row.get("to_status") == "CHURNED" and _in_period(row.get("changed_at"), start, end)
    }
    prev_reactivated = {
        int(row["guest_id"])
        for row in lifecycle
        if row.get("to_status") == "REACTIVATED" and _in_period(row.get("changed_at"), prev_start, start)
    }
    prev_lost = {
        int(row["guest_id"])
        for row in lifecycle
        if row.get("to_status") == "CHURNED" and _in_period(row.get("changed_at"), prev_start, start)
    }
    visits_total = sum(current_counts.values())
    prev_visits_total = sum(previous_counts.values())

    metric_values = {
        "unique_guests": (len(active), len(previous_active)),
        "new_guests": (len(new_guests), len(previous_new)),
        "new_module_guests": (
            len({int(row["guest_id"]) for row in new_module}),
            len({int(row["guest_id"]) for row in previous_module}),
        ),
        "reactivated_guests": (len(reactivated), len(prev_reactivated)),
        "average_visits": (
            round(visits_total / len(active), 2) if active else 0,
            round(prev_visits_total / len(previous_active), 2) if previous_active else 0,
        ),
        "lost_guests": (len(lost), len(prev_lost)),
    }
    metrics = {
        key: {"value": values[0], "previous": values[1], "change": _change(*values)}
        for key, values in metric_values.items()
    }

    snapshots = sources.get("score_history", [])
    current_state = _snapshot_state(snapshots, (end - timedelta(days=1)).date())
    previous_state = _snapshot_state(snapshots, (start - timedelta(days=1)).date())
    pulse_current = Counter(row["audience_type"] for row in current_state.values())
    pulse_previous = Counter(row["audience_type"] for row in previous_state.values())
    pulse = [
        {
            "code": code,
            "label": label,
            "count": pulse_current[code],
            "change": pulse_current[code] - pulse_previous[code],
        }
        for code, label in PULSE_LABELS.items()
    ]
    current_health = [
        float(row["health_score"]) for row in current_state.values() if row.get("health_score") is not None
    ]
    previous_health = [
        float(row["health_score"]) for row in previous_state.values() if row.get("health_score") is not None
    ]
    health_current = round(sum(current_health) / len(current_health), 1) if current_health else None
    health_previous = round(sum(previous_health) / len(previous_health), 1) if previous_health else None

    new_funnel = {
        "first": len(new_guests),
        "second": sum(len(visits_by_guest[guest_id]) >= 2 for guest_id in new_guests),
        "third": sum(len(visits_by_guest[guest_id]) >= 3 for guest_id in new_guests),
    }
    new_funnel["second_percent"] = _percent(new_funnel["second"], new_funnel["first"])
    new_funnel["third_percent"] = _percent(new_funnel["third"], new_funnel["first"])
    all_funnel = [
        {
            "visits": number,
            "count": sum(count >= number for count in current_counts.values()),
            "percent": _percent(sum(count >= number for count in current_counts.values()), len(active)),
        }
        for number in range(1, 6)
    ]

    cases = _mechanic_stats(
        [row for row in sources.get("case_openings", []) if _in_period(row.get("created_at"), start, end)], len(active)
    )
    wheel = _mechanic_stats(
        [row for row in sources.get("wheel_spins", []) if _in_period(row.get("created_at"), start, end)], len(active)
    )
    missions = _mechanic_stats(
        [row for row in sources.get("mission_completions", []) if _in_period(row.get("completed_at"), start, end)],
        len(active),
    )
    case_counts = Counter(
        int(row["guest_id"])
        for row in sources.get("case_openings", [])
        if _in_period(row.get("created_at"), start, end)
    )
    qualifying = {guest_id for guest_id, count in case_counts.items() if count > 1} | set(missions["guest_ids"])
    topups = [
        row
        for row in sources.get("topups", [])
        if _in_period(row.get("topup_at"), start, end) and 0 < float(row.get("amount") or 0) <= BALANCE_TOPUP_MAX_AMOUNT
    ]
    topup_by_guest = defaultdict(float)
    for row in topups:
        topup_by_guest[int(row["guest_id"])] += float(row.get("amount") or 0)
    qualifying_topups = {guest_id: topup_by_guest[guest_id] for guest_id in qualifying if topup_by_guest[guest_id] > 0}
    engaged_sum = round(sum(qualifying_topups.values()), 2)

    auto_campaigns, manual_campaigns = _campaigns(sources.get("mailing_recipients", []), visits_by_guest, topups, end)
    reactivation_campaigns = [
        row
        for row in auto_campaigns
        if any(
            token in f"{row.get('code')} {row.get('title')}".lower()
            for token in ("lost", "inactive", "churn", "risk", "потер")
        )
    ]
    reactivation_sent = sum(row["sent"] for row in reactivation_campaigns)
    reactivation_returned = sum(row["returned"] for row in reactivation_campaigns)
    reactivation_topups = round(sum(row["topup_amount"] for row in reactivation_campaigns), 2)
    case_users = set(cases["guest_ids"])
    case_with_topup = case_users & set(topup_by_guest)
    engaged_mechanics = case_users | set(missions["guest_ids"])
    current_frequency = (
        round(sum(current_counts.get(gid, 0) for gid in engaged_mechanics) / len(engaged_mechanics), 2)
        if engaged_mechanics
        else None
    )
    previous_frequency = (
        round(sum(previous_counts.get(gid, 0) for gid in engaged_mechanics) / len(engaged_mechanics), 2)
        if engaged_mechanics
        else None
    )

    quality = []
    if not current_state:
        quality.append("Нет снимка Пульса на конец месяца: блоки Пульса и Health показаны без значений.")
    elif any(row.get("reconstructed") for row in current_state.values()):
        quality.append("Пульс и Health частично восстановлены по историческим событиям.")
    estimated_module = sum(bool(row.get("is_estimated")) for row in new_module)
    if estimated_module:
        quality.append(f"Дата регистрации в Cyber Bonus приблизительно восстановлена для {estimated_module} гостей.")

    return {
        "version": REPORT_VERSION,
        "club": {
            "id": int(club["club_id"]),
            "name": club.get("name") or f"Клуб #{club['club_id']}",
            "timezone": club.get("timezone") or "Europe/Moscow",
        },
        "period": {
            "year": year,
            "month": month,
            "title": f"{MONTHS_RU[month]} {year}",
            "date_from": start.date().isoformat(),
            "date_to": (end - timedelta(days=1)).date().isoformat(),
            "generated_at": generated_at.isoformat(timespec="seconds"),
        },
        "metrics": metrics,
        "pulse": pulse,
        "health": {
            "average": health_current,
            "previous_average": health_previous,
            "change": (
                round(health_current - health_previous, 1)
                if health_current is not None and health_previous is not None
                else None
            ),
            "distribution": _health_distribution(current_state),
            "scored_guests": len(current_health),
        },
        "retention": {"new_guests": new_funnel, "all_guests": all_funnel},
        "crm": {
            "attribution_days": MONTHLY_REPORT_ATTRIBUTION_DAYS,
            "automatic": auto_campaigns,
            "best_manual": manual_campaigns[0] if manual_campaigns else None,
        },
        "gamification": {
            "cases": {key: value for key, value in cases.items() if key != "guest_ids"},
            "wheel": {key: value for key, value in wheel.items() if key != "guest_ids"},
            "missions": {key: value for key, value in missions.items() if key != "guest_ids"},
        },
        "engaged_revenue": {
            "guests": len(qualifying),
            "topped_up_guests": len(qualifying_topups),
            "amount": engaged_sum,
            "average_per_guest": round(engaged_sum / len(qualifying), 2) if qualifying else None,
        },
        "cyber_bonus_impact": {
            "reactivation": {
                "sent": reactivation_sent,
                "returned": reactivation_returned,
                "conversion_percent": _percent(reactivation_returned, reactivation_sent),
                "topup_amount": reactivation_topups,
            },
            "cases_to_topup": {
                "case_users": len(case_users),
                "topped_up_users": len(case_with_topup),
                "conversion_percent": _percent(len(case_with_topup), len(case_users)),
                "topup_amount": round(sum(topup_by_guest[guest_id] for guest_id in case_with_topup), 2),
            },
            "engaged_frequency": {
                "guests": len(engaged_mechanics),
                "current": current_frequency,
                "previous": previous_frequency,
                "change": (
                    round(current_frequency - previous_frequency, 2)
                    if current_frequency is not None and previous_frequency is not None
                    else None
                ),
                "change_percent": (
                    round((current_frequency / previous_frequency - 1) * 100, 1)
                    if current_frequency is not None and previous_frequency
                    else None
                ),
            },
        },
        "data_quality": quality,
    }


def _rows(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _latest_score_rows(conn, club_id: int, cutoff: date) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT h.guest_id,h.snapshot_date,h.health_score,
               h.lifecycle_status,h.detail_json,h.reconstructed
        FROM guest_score_history h
        JOIN (
            SELECT guest_id,MAX(snapshot_date) AS snapshot_date
            FROM guest_score_history
            WHERE club_id=%s AND snapshot_date<=%s
            GROUP BY guest_id
        ) latest
          ON latest.guest_id=h.guest_id
         AND latest.snapshot_date=h.snapshot_date
        WHERE h.club_id=%s
        """,
        (club_id, cutoff, club_id),
    )


def _localize(rows: list[dict[str, Any]], fields: tuple[str, ...], timezone_name: str) -> None:
    for row in rows:
        for field in fields:
            if row.get(field) is not None:
                row[field] = utc_datetime_to_club_local(row[field], timezone_name)


def calculate_monthly_report(conn, club_id: int, year: int, month: int) -> dict[str, Any]:
    start, end = month_bounds(year, month)
    with conn.cursor() as cursor:
        cursor.execute("SELECT club_id, name, timezone FROM clubs WHERE club_id=%s LIMIT 1", (club_id,))
        club = cursor.fetchone()
    if not club:
        raise ValueError("Клуб не найден")
    timezone_name = club.get("timezone") or "Europe/Moscow"
    now = get_club_local_now(timezone_name)
    if start > now:
        raise ValueError("Нельзя сформировать отчёт за будущий месяц")
    utc_start = club_local_datetime_to_utc(start, timezone_name)
    utc_end = club_local_datetime_to_utc(end, timezone_name)

    sources = {
        "sessions": _rows(
            conn,
            "SELECT guest_id,date_start,date_stop FROM guest_sessions WHERE club_id=%s AND guest_id IS NOT NULL AND date_start IS NOT NULL AND date_stop>date_start ORDER BY guest_id,date_start",
            (club_id,),
        ),
        "module_registrations": _rows(
            conn, "SELECT guest_id,registered_at,is_estimated FROM module_registrations WHERE club_id=%s", (club_id,)
        ),
        "lifecycle_events": _rows(
            conn,
            "SELECT guest_id,to_status,changed_at,reconstructed FROM guest_lifecycle_events WHERE club_id=%s",
            (club_id,),
        ),
        "score_history": _latest_score_rows(conn, club_id, (start - timedelta(days=1)).date())
        + _latest_score_rows(conn, club_id, (end - timedelta(days=1)).date()),
        "case_openings": _rows(
            conn,
            "SELECT guest_id,created_at FROM guest_case_openings WHERE club_id=%s AND created_at>=%s AND created_at<%s",
            (club_id, utc_start, utc_end),
        ),
        "wheel_spins": _rows(
            conn,
            "SELECT guest_id,created_at FROM guest_wheel_spins WHERE club_id=%s AND created_at>=%s AND created_at<%s",
            (club_id, utc_start, utc_end),
        ),
        "mission_completions": _rows(
            conn,
            "SELECT guest_id,completed_at FROM guest_mission_completions WHERE club_id=%s AND completed_at>=%s AND completed_at<%s",
            (club_id, utc_start, utc_end),
        ),
        "topups": _rows(
            conn,
            "SELECT guest_id,amount,topup_at FROM guest_balance_topups WHERE club_id=%s AND topup_at>=%s AND topup_at<%s AND amount>0 AND amount<=%s",
            (club_id, utc_start, utc_end, BALANCE_TOPUP_MAX_AMOUNT),
        ),
        "mailing_recipients": _rows(
            conn,
            """
            SELECT m.id AS mailing_id,m.filters_json,m.message_text,mr.guest_id,mr.status,
                   COALESCE(mr.sent_at,m.started_at,m.created_at) AS interaction_at,
                   ams.title AS scenario_title
            FROM mailings m
            JOIN mailing_recipients mr ON mr.mailing_id=m.id
            LEFT JOIN auto_mailing_settings ams ON ams.club_id=m.club_id
              AND ams.code=JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json,'{}'),'$.auto_mailing'))
            WHERE m.club_id=%s AND COALESCE(mr.sent_at,m.started_at,m.created_at)>=%s
              AND COALESCE(mr.sent_at,m.started_at,m.created_at)<%s
        """,
            (club_id, utc_start, utc_end),
        ),
    }
    for key, fields in {
        "sessions": ("date_start", "date_stop"),
        "module_registrations": ("registered_at",),
        "lifecycle_events": ("changed_at",),
        "case_openings": ("created_at",),
        "wheel_spins": ("created_at",),
        "mission_completions": ("completed_at",),
        "topups": ("topup_at",),
        "mailing_recipients": ("interaction_at",),
    }.items():
        _localize(sources[key], fields, timezone_name)
    return build_report_from_sources(sources, club, year, month, generated_at=now)


def json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        default=lambda value: float(value) if isinstance(value, Decimal) else value.isoformat(),
    )
