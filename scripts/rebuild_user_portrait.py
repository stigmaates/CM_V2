import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor

from app.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        ssl={"check_hostname": False},
    )


def gender_to_int(gender: Optional[str]) -> Optional[int]:
    if gender is None:
        return None
    value = gender.strip().lower()
    if value in {"male", "m", "man", "м", "муж", "мужской"}:
        return 1
    if value in {"female", "f", "woman", "ж", "жен", "женский"}:
        return 2
    return None


def calc_age(birth_date: Optional[datetime], today: datetime) -> Optional[int]:
    if not birth_date:
        return None

    if isinstance(birth_date, datetime):
        bd = birth_date.date()
    elif isinstance(birth_date, date):
        bd = birth_date
    else:
        return None

    years = today.date().year - bd.year
    if (today.date().month, today.date().day) < (bd.month, bd.day):
        years -= 1
    return years


def calc_favorite_period(day_count: int, evening_count: int, night_count: int) -> Optional[str]:
    if day_count == 0 and evening_count == 0 and night_count == 0:
        return None
    if day_count >= evening_count and day_count >= night_count:
        return "day"
    if evening_count >= night_count:
        return "evening"
    return "night"


def calc_crm_type(total_visits: int, visits_90d: int, days_since_last_visit: Optional[int]) -> str:
    """
    Финальная логика:
    - no_visits: ни одного визита вообще
    - dead: последний визит 90+ дней назад
    - lost: последний визит 30-89 дней назад
    - risk: последний визит 14-29 дней назад
    - top: 15+ визитов за 90 дней
    - rare: 0-9 визитов за 90 дней, если не попал в risk/lost/dead
    - base: 10-14 визитов за 90 дней
    """

    if total_visits <= 0:
        return "no_visits"

    if days_since_last_visit is not None:
        if days_since_last_visit >= 90:
            return "dead"
        if days_since_last_visit >= 30:
            return "lost"
        if days_since_last_visit >= 14:
            return "risk"

    if visits_90d >= 15:
        return "top"
    if visits_90d <= 9:
        return "rare"
    return "base"


def fetch_guests(conn) -> Dict[Tuple[int, int], Dict[str, Any]]:
    sql = """
        SELECT
            guest_id,
            club_id,
            phone,
            birth_date,
            date_insert,
            telegram_id,
            gender
        FROM guests
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return {(int(row["club_id"]), int(row["guest_id"])): row for row in rows}


def collapse_sessions_to_visits(rows: List[Dict[str, Any]], gap_hours: int = 2) -> List[Dict[str, datetime]]:
    visits: List[Dict[str, datetime]] = []
    max_gap = timedelta(hours=gap_hours)

    for row in sorted(rows, key=lambda item: item["date_start"]):
        date_start = row.get("date_start")
        date_stop = row.get("date_stop")
        if not date_start or not date_stop:
            continue

        if not visits or date_start - visits[-1]["date_stop"] > max_gap:
            visits.append({"date_start": date_start, "date_stop": date_stop})
            continue

        if date_stop > visits[-1]["date_stop"]:
            visits[-1]["date_stop"] = date_stop

    return visits


def fetch_sessions_agg(conn, now: datetime) -> Dict[Tuple[int, int], Dict[str, Any]]:
    sql = """
        SELECT
            club_id,
            guest_id,
            date_start,
            date_stop
        FROM guest_sessions
        WHERE club_id IS NOT NULL
          AND guest_id IS NOT NULL
          AND date_start IS NOT NULL
          AND date_stop IS NOT NULL
        ORDER BY club_id, guest_id, date_start
    """

    result: Dict[Tuple[int, int], Dict[str, Any]] = defaultdict(
        lambda: {
            "first_visit_date": None,
            "last_visit_date": None,
            "visits_7d": 0,
            "visits_30d": 0,
            "visits_90d": 0,
            "total_visits": 0,
            "avg_session_minutes": None,
            "max_session_minutes": 0,
            "total_hours_30d": 0.0,
            "total_hours_all": 0.0,
            "days_since_last_visit": None,
            "night_share": None,
            "weekend_share": None,
            "favorite_period": None,
            "avg_days_between_visits": None,
            "lifetime_days": None,
            "is_active_30d": 0,
            "is_active_90d": 0,
            "avg_visits_per_month": None,
        }
    )

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    sessions_by_guest: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    visit_minutes_sum: Dict[Tuple[int, int], float] = defaultdict(float)
    night_count: Dict[Tuple[int, int], int] = defaultdict(int)
    weekend_count: Dict[Tuple[int, int], int] = defaultdict(int)
    day_period_count: Dict[Tuple[int, int], int] = defaultdict(int)
    evening_period_count: Dict[Tuple[int, int], int] = defaultdict(int)
    night_period_count: Dict[Tuple[int, int], int] = defaultdict(int)

    for row in rows:
        key = (int(row["club_id"]), int(row["guest_id"]))
        sessions_by_guest[key].append(row)
        agg = result[key]

    for key, guest_sessions in sessions_by_guest.items():
        agg = result[key]
        visits = collapse_sessions_to_visits(guest_sessions)

        for visit in visits:
            date_start = visit["date_start"]
            date_stop = visit["date_stop"]
            duration_minutes = max((date_stop - date_start).total_seconds() / 60.0, 0.0)

            agg["total_visits"] += 1
            visit_minutes_sum[key] += duration_minutes
            agg["max_session_minutes"] = max(agg["max_session_minutes"], int(duration_minutes))
            agg["total_hours_all"] += duration_minutes / 60.0

            if agg["first_visit_date"] is None or date_start < agg["first_visit_date"]:
                agg["first_visit_date"] = date_start
            if agg["last_visit_date"] is None or date_start > agg["last_visit_date"]:
                agg["last_visit_date"] = date_start

            if date_start >= now - timedelta(days=7):
                agg["visits_7d"] += 1
            if date_start >= now - timedelta(days=30):
                agg["visits_30d"] += 1
                agg["total_hours_30d"] += duration_minutes / 60.0
                agg["is_active_30d"] = 1
            if date_start >= now - timedelta(days=90):
                agg["visits_90d"] += 1
                agg["is_active_90d"] = 1

            hour = date_start.hour
            weekday = date_start.weekday()  # 0=Mon ... 6=Sun

            if hour >= 22 or hour < 8:
                night_count[key] += 1
                night_period_count[key] += 1
            elif 8 <= hour <= 16:
                day_period_count[key] += 1
            else:
                evening_period_count[key] += 1

            if weekday >= 5:
                weekend_count[key] += 1

    for key, agg in result.items():
        total_visits = agg["total_visits"]

        if total_visits > 0:
            agg["avg_session_minutes"] = visit_minutes_sum[key] / total_visits
            agg["night_share"] = night_count[key] / total_visits
            agg["weekend_share"] = weekend_count[key] / total_visits
            agg["favorite_period"] = calc_favorite_period(
                day_period_count[key],
                evening_period_count[key],
                night_period_count[key],
            )

        visits = collapse_sessions_to_visits(sessions_by_guest.get(key, []))
        starts = [visit["date_start"] for visit in visits]
        if starts:
            agg["days_since_last_visit"] = (now.date() - starts[-1].date()).days
            agg["lifetime_days"] = max((now.date() - starts[0].date()).days, 0)

            if len(starts) >= 2:
                gaps = []
                for i in range(1, len(starts)):
                    gaps.append((starts[i].date() - starts[i - 1].date()).days)
                agg["avg_days_between_visits"] = sum(gaps) / len(gaps)

            months = max(
                (now.year - starts[0].year) * 12 + (now.month - starts[0].month),
                1,
            )
            agg["avg_visits_per_month"] = total_visits / months

    return result


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return digits or None


def fetch_topups_agg(conn, now: datetime) -> Dict[Tuple[int, int], Dict[str, Any]]:
    sql = """
        SELECT
            club_id,
            guest_id,
            amount,
            topup_at
        FROM guest_balance_topups
        WHERE club_id IS NOT NULL
          AND guest_id IS NOT NULL
    """

    result: Dict[Tuple[int, int], Dict[str, Any]] = defaultdict(
        lambda: {
            "avg_check_all": None,
            "avg_check_30d": None,
            "last_payment_date": None,
        }
    )

    topups_all: Dict[Tuple[int, int], List[float]] = defaultdict(list)
    topups_30d: Dict[Tuple[int, int], List[float]] = defaultdict(list)
    topup_dates: Dict[Tuple[int, int], List[datetime]] = defaultdict(list)

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    for row in rows:
        if row.get("guest_id") is None:
            continue

        key = (int(row["club_id"]), int(row["guest_id"]))
        amount = float(row["amount"]) if row["amount"] is not None else None
        dt = row["topup_at"]

        if amount is not None:
            topups_all[key].append(amount)
            if dt and dt >= now - timedelta(days=30):
                topups_30d[key].append(amount)

        if dt:
            topup_dates[key].append(dt)

    all_keys = set(topups_all) | set(topups_30d) | set(topup_dates)

    for key in all_keys:
        agg = result[key]
        if topups_all[key]:
            agg["avg_check_all"] = sum(topups_all[key]) / len(topups_all[key])
        if topups_30d[key]:
            agg["avg_check_30d"] = sum(topups_30d[key]) / len(topups_30d[key])
        if topup_dates[key]:
            agg["last_payment_date"] = max(topup_dates[key])

    return result


def fetch_spins_agg(conn) -> Dict[Tuple[int, int], Dict[str, Any]]:
    sql = """
        SELECT
            club_id,
            guest_id,
            COUNT(*) AS spins_count,
            MAX(created_at) AS last_spin_date
        FROM guest_wheel_spins
        WHERE club_id IS NOT NULL
          AND guest_id IS NOT NULL
        GROUP BY club_id, guest_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    result: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for row in rows:
        key = (int(row["club_id"]), int(row["guest_id"]))
        result[key] = {
            "spins_count": int(row["spins_count"] or 0),
            "last_spin_date": row["last_spin_date"],
        }
    return result


def build_records(conn) -> List[Dict[str, Any]]:
    now = datetime.now()

    guests = fetch_guests(conn)
    sessions = fetch_sessions_agg(conn, now)
    topups = fetch_topups_agg(conn, now)
    spins = fetch_spins_agg(conn)

    records: List[Dict[str, Any]] = []

    for guest_key, g in guests.items():
        if isinstance(guest_key, tuple):
            club_id, guest_id = guest_key
        else:
            club_id = int(g.get("club_id"))
            guest_id = int(guest_key)

        key = (club_id, guest_id)
        sess = sessions.get(key, {})
        ops = topups.get(key, {})
        spn = spins.get(key, {})

        birth_date = g.get("birth_date")
        age = calc_age(birth_date, now)

        total_visits = sess.get("total_visits", 0)
        visits_90d = sess.get("visits_90d", 0)
        days_since_last_visit = sess.get("days_since_last_visit")

        crm_type = calc_crm_type(
            total_visits=total_visits, visits_90d=visits_90d, days_since_last_visit=days_since_last_visit
        )

        record = {
            "guest_id": guest_id,
            "club_id": club_id,
            "gender": gender_to_int(g.get("gender")),
            "age": age,
            "registration_date": g.get("date_insert"),
            "first_visit_date": sess.get("first_visit_date"),
            "last_visit_date": sess.get("last_visit_date"),
            "crm_type": crm_type,
            "visits_7d": sess.get("visits_7d", 0),
            "visits_30d": sess.get("visits_30d", 0),
            "visits_90d": visits_90d,
            "total_visits": total_visits,
            "avg_visits_per_month": sess.get("avg_visits_per_month"),
            "avg_session_minutes": sess.get("avg_session_minutes"),
            "max_session_minutes": sess.get("max_session_minutes", 0),
            "total_hours_30d": sess.get("total_hours_30d", 0.0),
            "total_hours_all": sess.get("total_hours_all", 0.0),
            "days_since_last_visit": days_since_last_visit,
            "night_share": sess.get("night_share"),
            "weekend_share": sess.get("weekend_share"),
            "favorite_period": sess.get("favorite_period"),
            "avg_check_all": ops.get("avg_check_all"),
            "avg_check_30d": ops.get("avg_check_30d"),
            "last_payment_date": ops.get("last_payment_date"),
            "missions_completed_count": 0,
            "missions_in_progress_count": 0,
            "last_mission_activity_date": None,
            "spins_count": spn.get("spins_count", 0),
            "last_spin_date": spn.get("last_spin_date"),
            "lifetime_days": sess.get("lifetime_days"),
            "avg_days_between_visits": sess.get("avg_days_between_visits"),
            "is_active_30d": sess.get("is_active_30d", 0),
            "is_active_90d": sess.get("is_active_90d", 0),
            "has_telegram": 1 if g.get("telegram_id") is not None else 0,
        }
        records.append(record)

    return records


def upsert_user_portrait(conn, records: List[Dict[str, Any]]) -> None:
    if not records:
        return

    sql = """
        INSERT INTO user_portrait (
            guest_id,
            club_id,
            gender,
            age,
            registration_date,
            first_visit_date,
            last_visit_date,
            crm_type,
            visits_7d,
            visits_30d,
            visits_90d,
            total_visits,
            avg_visits_per_month,
            avg_session_minutes,
            max_session_minutes,
            total_hours_30d,
            total_hours_all,
            days_since_last_visit,
            night_share,
            weekend_share,
            favorite_period,
            avg_check_all,
            avg_check_30d,
            last_payment_date,
            missions_completed_count,
            missions_in_progress_count,
            last_mission_activity_date,
            spins_count,
            last_spin_date,
            lifetime_days,
            avg_days_between_visits,
            is_active_30d,
            is_active_90d,
            has_telegram
        )
        VALUES (
            %(guest_id)s,
            %(club_id)s,
            %(gender)s,
            %(age)s,
            %(registration_date)s,
            %(first_visit_date)s,
            %(last_visit_date)s,
            %(crm_type)s,
            %(visits_7d)s,
            %(visits_30d)s,
            %(visits_90d)s,
            %(total_visits)s,
            %(avg_visits_per_month)s,
            %(avg_session_minutes)s,
            %(max_session_minutes)s,
            %(total_hours_30d)s,
            %(total_hours_all)s,
            %(days_since_last_visit)s,
            %(night_share)s,
            %(weekend_share)s,
            %(favorite_period)s,
            %(avg_check_all)s,
            %(avg_check_30d)s,
            %(last_payment_date)s,
            %(missions_completed_count)s,
            %(missions_in_progress_count)s,
            %(last_mission_activity_date)s,
            %(spins_count)s,
            %(last_spin_date)s,
            %(lifetime_days)s,
            %(avg_days_between_visits)s,
            %(is_active_30d)s,
            %(is_active_90d)s,
            %(has_telegram)s
        )
        ON DUPLICATE KEY UPDATE
            club_id = VALUES(club_id),
            gender = VALUES(gender),
            age = VALUES(age),
            registration_date = VALUES(registration_date),
            first_visit_date = VALUES(first_visit_date),
            last_visit_date = VALUES(last_visit_date),
            crm_type = VALUES(crm_type),
            visits_7d = VALUES(visits_7d),
            visits_30d = VALUES(visits_30d),
            visits_90d = VALUES(visits_90d),
            total_visits = VALUES(total_visits),
            avg_visits_per_month = VALUES(avg_visits_per_month),
            avg_session_minutes = VALUES(avg_session_minutes),
            max_session_minutes = VALUES(max_session_minutes),
            total_hours_30d = VALUES(total_hours_30d),
            total_hours_all = VALUES(total_hours_all),
            days_since_last_visit = VALUES(days_since_last_visit),
            night_share = VALUES(night_share),
            weekend_share = VALUES(weekend_share),
            favorite_period = VALUES(favorite_period),
            avg_check_all = VALUES(avg_check_all),
            avg_check_30d = VALUES(avg_check_30d),
            last_payment_date = VALUES(last_payment_date),
            missions_completed_count = VALUES(missions_completed_count),
            missions_in_progress_count = VALUES(missions_in_progress_count),
            last_mission_activity_date = VALUES(last_mission_activity_date),
            spins_count = VALUES(spins_count),
            last_spin_date = VALUES(last_spin_date),
            lifetime_days = VALUES(lifetime_days),
            avg_days_between_visits = VALUES(avg_days_between_visits),
            is_active_30d = VALUES(is_active_30d),
            is_active_90d = VALUES(is_active_90d),
            has_telegram = VALUES(has_telegram),
            updated_at = CURRENT_TIMESTAMP
    """

    with conn.cursor() as cur:
        cur.executemany(sql, records)


def cleanup_deleted_guests(conn) -> None:
    sql = """
        DELETE up
        FROM user_portrait up
        LEFT JOIN guests g
          ON g.club_id = up.club_id
         AND g.guest_id = up.guest_id
        WHERE g.guest_id IS NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql)


def rebuild_user_portrait():
    conn = get_connection()
    try:
        records = build_records(conn)
        upsert_user_portrait(conn, records)
        cleanup_deleted_guests(conn)
        conn.commit()
        print(f"OK: user_portrait updated, rows processed: {len(records)}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    rebuild_user_portrait()
