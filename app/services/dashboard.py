from collections import defaultdict
from datetime import datetime, timedelta

from app.core import calc_percent_change, get_db_connection, get_period_range
from app.services.missions import get_club_missions


def _round_display(value):
    """Округляет значения для отображения на дашборде без дробной части."""
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def get_unique_guests_chart(club_id: int, period_days: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            now = datetime.now()
            end_dt = now

            if period_days == 7:
                start_dt = now - timedelta(days=6)
                labels = []
                values_map = {}

                cursor.execute(
                    """
                    SELECT DATE(date_start) AS d, COUNT(DISTINCT guest_id) AS cnt
                    FROM guest_sessions
                    WHERE club_id = %s
                      AND date_start >= %s
                      AND date_start < %s
                    GROUP BY DATE(date_start)
                    ORDER BY DATE(date_start)
                    """,
                    (club_id, start_dt.replace(hour=0, minute=0, second=0, microsecond=0), end_dt),
                )

                rows = cursor.fetchall()
                for row in rows:
                    values_map[row["d"].strftime("%d.%m")] = row["cnt"]

                current_day = start_dt.date()
                last_day = now.date()

                while current_day <= last_day:
                    labels.append(current_day.strftime("%d.%m"))
                    current_day += timedelta(days=1)

                values = [values_map.get(label, 0) for label in labels]

                return {"title": "Уникальные гости по дням", "labels": labels, "values": values}

            if period_days == 30:
                start_dt = now - timedelta(days=29)
                start_week = start_dt.date() - timedelta(days=start_dt.weekday())
                end_week = now.date() - timedelta(days=now.weekday())

                cursor.execute(
                    """
                    SELECT YEAR(date_start) AS y,
                           WEEK(date_start, 1) AS w,
                           COUNT(DISTINCT guest_id) AS cnt
                    FROM guest_sessions
                    WHERE club_id = %s
                      AND date_start >= %s
                      AND date_start < %s
                    GROUP BY YEAR(date_start), WEEK(date_start, 1)
                    ORDER BY YEAR(date_start), WEEK(date_start, 1)
                    """,
                    (club_id, start_dt.replace(hour=0, minute=0, second=0, microsecond=0), end_dt),
                )

                rows = cursor.fetchall()
                values_map = {f'{row["y"]}-{row["w"]}': row["cnt"] for row in rows}

                labels = []
                values = []
                current_week = start_week
                while current_week <= end_week:
                    iso_year, iso_week, _ = current_week.isocalendar()
                    key = f"{iso_year}-{iso_week}"
                    labels.append(current_week.strftime("%d.%m"))
                    values.append(values_map.get(key, 0))
                    current_week += timedelta(days=7)

                return {"title": "Уникальные гости по неделям", "labels": labels, "values": values}

            start_dt = now - timedelta(days=89)
            cursor.execute(
                """
                SELECT YEAR(date_start) AS y,
                       MONTH(date_start) AS m,
                       COUNT(DISTINCT guest_id) AS cnt
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start >= %s
                  AND date_start < %s
                GROUP BY YEAR(date_start), MONTH(date_start)
                ORDER BY YEAR(date_start), MONTH(date_start)
                """,
                (club_id, start_dt.replace(hour=0, minute=0, second=0, microsecond=0), end_dt),
            )

            rows = cursor.fetchall()
            values_map = {f'{row["y"]}-{row["m"]}': row["cnt"] for row in rows}
            month_names = {
                1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр",
                5: "Май", 6: "Июн", 7: "Июл", 8: "Авг",
                9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек",
            }

            labels = []
            values = []
            current = start_dt.replace(day=1).date()
            end_month = now.replace(day=1).date()

            while current <= end_month:
                key = f"{current.year}-{current.month}"
                labels.append(month_names[current.month])
                values.append(values_map.get(key, 0))
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)

            return {"title": "Уникальные гости по месяцам", "labels": labels, "values": values}
    finally:
        conn.close()


def get_dashboard_stats(club_id: int, period_days: int = 30):
    if not club_id:
        return None

    now = datetime.now()
    current_end = now
    current_start = now - timedelta(days=period_days)
    previous_end = current_start
    previous_start = current_start - timedelta(days=period_days)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(DISTINCT guest_id) AS cnt
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start >= %s
                  AND date_start < %s
                """,
                (club_id, current_start, current_end),
            )
            guests_current = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(DISTINCT guest_id) AS cnt
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start >= %s
                  AND date_start < %s
                """,
                (club_id, previous_start, previous_end),
            )
            guests_previous = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM (
                    SELECT guest_id
                    FROM guest_sessions
                    WHERE club_id = %s
                      AND date_start >= %s
                      AND date_start < %s
                    GROUP BY guest_id
                    HAVING COUNT(*) >= 2
                ) t
                """,
                (club_id, current_start, current_end),
            )
            returned_guests_current = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM (
                    SELECT guest_id
                    FROM guest_sessions
                    WHERE club_id = %s
                      AND date_start >= %s
                      AND date_start < %s
                    GROUP BY guest_id
                    HAVING COUNT(*) >= 2
                ) t
                """,
                (club_id, previous_start, previous_end),
            )
            returned_guests_previous = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(*) AS operations_count,
                       COALESCE(SUM(`sum`), 0) AS total_sum,
                       COALESCE(AVG(`sum`), 0) AS avg_check
                FROM operations_log
                WHERE club_id = %s
                  AND type = 'plus'
                  AND date_normal >= %s
                  AND date_normal < %s
                """,
                (club_id, current_start, current_end),
            )
            avg_check_current_row = cursor.fetchone()

            operations_count_current = avg_check_current_row["operations_count"] or 0
            total_sum_current = float(avg_check_current_row["total_sum"] or 0)
            avg_check_current = float(avg_check_current_row["avg_check"] or 0)

            cursor.execute(
                """
                SELECT COUNT(*) AS operations_count,
                       COALESCE(SUM(`sum`), 0) AS total_sum,
                       COALESCE(AVG(`sum`), 0) AS avg_check
                FROM operations_log
                WHERE club_id = %s
                  AND type = 'plus'
                  AND date_normal >= %s
                  AND date_normal < %s
                """,
                (club_id, previous_start, previous_end),
            )
            avg_check_previous_row = cursor.fetchone()

            operations_count_previous = avg_check_previous_row["operations_count"] or 0
            total_sum_previous = float(avg_check_previous_row["total_sum"] or 0)
            avg_check_previous = float(avg_check_previous_row["avg_check"] or 0)

            cursor.execute("SELECT COUNT(*) AS cnt FROM guests WHERE club_id = %s", (club_id,))
            total_guests = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM guests
                WHERE club_id = %s
                  AND telegram_id IS NOT NULL
                  AND TRIM(CAST(telegram_id AS CHAR)) <> ''
                """,
                (club_id,),
            )
            guests_with_telegram = cursor.fetchone()["cnt"] or 0

            csi_percent = _round_display((guests_with_telegram / total_guests) * 100) if total_guests > 0 else 0
            mailing_count = guests_with_telegram

        guests_diff = guests_current - guests_previous
        guests_diff_percent = _round_display(calc_percent_change(guests_current, guests_previous))

        retention_current = _round_display((returned_guests_current / guests_current) * 100) if guests_current > 0 else 0
        retention_previous = _round_display((returned_guests_previous / guests_previous) * 100) if guests_previous > 0 else 0
        retention_diff = _round_display(retention_current - retention_previous)

        avg_check_current = _round_display(avg_check_current)
        avg_check_previous = _round_display(avg_check_previous)
        avg_check_diff = _round_display(avg_check_current - avg_check_previous)
        avg_check_diff_percent = _round_display(calc_percent_change(avg_check_current, avg_check_previous))

        chart_data = get_unique_guests_chart(club_id, period_days)

        result = {
            "period_days": period_days,
            "guests_current": guests_current,
            "guests_previous": guests_previous,
            "guests_diff": guests_diff,
            "guests_diff_percent": guests_diff_percent,
            "retention_current": retention_current,
            "retention_previous": retention_previous,
            "retention_diff": retention_diff,
            "avg_check_current": avg_check_current,
            "avg_check_previous": avg_check_previous,
            "avg_check_diff": avg_check_diff,
            "avg_check_diff_percent": avg_check_diff_percent,
            "operations_count_current": operations_count_current,
            "operations_count_previous": operations_count_previous,
            "total_sum_current": _round_display(total_sum_current),
            "total_sum_previous": _round_display(total_sum_previous),
            "csi_percent": csi_percent,
            "csi_linked_guests": guests_with_telegram,
            "csi_total_guests": total_guests,
            "mailing_count": mailing_count,
            "chart": chart_data,
            "debug": {
                "club_id": club_id,
                "current_start": str(current_start),
                "current_end": str(current_end),
                "previous_start": str(previous_start),
                "previous_end": str(previous_end),
            },
        }

        print("DASHBOARD RESULT:", result)
        return result
    finally:
        conn.close()


def _get_total_club_guests(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM guests
                WHERE club_id = %s
                """,
                (club_id,),
            )
            return cursor.fetchone()["cnt"] or 0
    finally:
        conn.close()


def _get_sessions_by_guest_for_period(club_id: int, current_start, current_end):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT guest_id, date_start, date_stop
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start >= %s
                  AND date_start < %s
                ORDER BY guest_id, date_start
                """,
                (club_id, current_start, current_end),
            )
            rows = cursor.fetchall()

        sessions_by_guest = defaultdict(list)
        for row in rows:
            sessions_by_guest[row["guest_id"]].append(row)

        return sessions_by_guest
    finally:
        conn.close()


def _get_first_spin_by_guest_for_period(club_id: int, current_start, current_end):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT guest_id, MIN(created_at) AS first_spin_at
                FROM guest_wheel_spins
                WHERE club_id = %s
                  AND created_at >= %s
                  AND created_at < %s
                GROUP BY guest_id
                """,
                (club_id, current_start, current_end),
            )
            rows = cursor.fetchall()

        return {
            row["guest_id"]: row["first_spin_at"]
            for row in rows
            if row["first_spin_at"] is not None
        }
    finally:
        conn.close()


def _session_matches_mission(session_row, mission):
    date_start = session_row.get("date_start")
    date_stop = session_row.get("date_stop")

    if not date_start:
        return False

    mission_start = mission.get("start_at")
    mission_end = mission.get("end_at")

    if mission_start and date_start < mission_start:
        return False
    if mission_end and date_start > mission_end:
        return False

    metric = mission.get("target_metric")

    if metric == "visits_count":
        return True

    if metric == "night_visits_count":
        return date_start.hour >= 22 or date_start.hour < 8

    if metric == "weekend_visits_count":
        # 6 = Saturday, 7 = Sunday
        return date_start.isoweekday() in (6, 7)

    if metric == "long_visits_count":
        if not date_stop:
            return False

        config = mission.get("config") or {}
        min_hours = 0
        if isinstance(config, dict):
            min_hours = int(config.get("min_hours", 0) or 0)

        duration_hours = (date_stop - date_start).total_seconds() / 3600
        return duration_hours >= min_hours

    return False


def _get_mission_completion_at_from_sessions(guest_sessions, mission):
    target = int(mission.get("target_amount") or 0)
    if target <= 0:
        return None

    matched_dates = []

    for session_row in guest_sessions:
        if _session_matches_mission(session_row, mission):
            matched_dates.append(session_row["date_start"])

    if len(matched_dates) >= target:
        return matched_dates[target - 1]

    return None


def get_dashboard_engagement_stats(club_id: int, period_days: int = 30):
    ranges = get_period_range(period_days)
    current_start = ranges["current_start"]
    current_end = ranges["current_end"]

    total_guests = _get_total_club_guests(club_id)
    sessions_by_guest = _get_sessions_by_guest_for_period(club_id, current_start, current_end)

    # -------------------------
    # WHEEL
    # -------------------------
    first_spin_by_guest = _get_first_spin_by_guest_for_period(club_id, current_start, current_end)

    wheel_spun_guests = len(first_spin_by_guest)
    wheel_returned_guests = 0

    for guest_id, first_spin_at in first_spin_by_guest.items():
        guest_sessions = sessions_by_guest.get(guest_id, [])
        returned = any(
            session_row["date_start"] and session_row["date_start"] > first_spin_at
            for session_row in guest_sessions
        )
        if returned:
            wheel_returned_guests += 1

    wheel_engagement_percent = _round_display((wheel_spun_guests / total_guests) * 100) if total_guests > 0 else 0

    # -------------------------
    # MISSIONS
    # -------------------------
    active_missions = get_club_missions(club_id)

    mission_completed_guests = 0
    mission_returned_guests = 0

    for guest_id, guest_sessions in sessions_by_guest.items():
        completion_dates = []

        for mission in active_missions:
            completion_at = _get_mission_completion_at_from_sessions(guest_sessions, mission)
            if completion_at:
                completion_dates.append(completion_at)

        if completion_dates:
            mission_completed_guests += 1
            first_completion_at = min(completion_dates)

            returned = any(
                session_row["date_start"] and session_row["date_start"] > first_completion_at
                for session_row in guest_sessions
            )
            if returned:
                mission_returned_guests += 1

    mission_engagement_percent = _round_display((mission_completed_guests / total_guests) * 100) if total_guests > 0 else 0

    return {
        "wheel": {
            "total_guests": total_guests,
            "involved_guests": wheel_spun_guests,
            "engagement_percent": wheel_engagement_percent,
            "returned_guests": wheel_returned_guests,
        },
        "missions": {
            "total_guests": total_guests,
            "involved_guests": mission_completed_guests,
            "engagement_percent": mission_engagement_percent,
            "returned_guests": mission_returned_guests,
        },
    }


def get_dashboard_audience_stats(club_id: int) -> dict:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT crm_type, COUNT(*) AS cnt
                FROM user_portrait
                WHERE club_id = %s
                GROUP BY crm_type
                """,
                (club_id,),
            )
            rows = cursor.fetchall()

        audience = {
            "top": 0,
            "base": 0,
            "rare": 0,
            "risk": 0,
            "lost": 0,
            "dead": 0,
            "no_visits": 0,
            "total": 0,
        }

        for row in rows:
            crm_type = row["crm_type"]
            cnt = int(row["cnt"] or 0)

            if crm_type in audience:
                audience[crm_type] = cnt
                audience["total"] += cnt

        return audience
    finally:
        conn.close()


def get_visit_heatmap_stats(club_id: int, period_days: int = 30) -> dict:
    """Возвращает heatmap посещений: дни недели x часы.

    Считаем количество сессий по date_start за выбранный период.
    Уровень 0-5 нужен только для CSS-интенсивности ячейки.
    """
    if period_days not in (7, 30, 90):
        period_days = 30

    now = datetime.now()
    current_start = now - timedelta(days=period_days)
    current_end = now

    days = [
        {"index": 0, "label": "Пн", "full": "Понедельник"},
        {"index": 1, "label": "Вт", "full": "Вторник"},
        {"index": 2, "label": "Ср", "full": "Среда"},
        {"index": 3, "label": "Чт", "full": "Четверг"},
        {"index": 4, "label": "Пт", "full": "Пятница"},
        {"index": 5, "label": "Сб", "full": "Суббота"},
        {"index": 6, "label": "Вс", "full": "Воскресенье"},
    ]
    hours = list(range(24))
    values = {(day["index"], hour): 0 for day in days for hour in hours}

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT WEEKDAY(date_start) AS weekday_idx,
                       HOUR(date_start) AS hour_idx,
                       COUNT(*) AS visits_count
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start >= %s
                  AND date_start < %s
                GROUP BY WEEKDAY(date_start), HOUR(date_start)
                ORDER BY WEEKDAY(date_start), HOUR(date_start)
                """,
                (club_id, current_start, current_end),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    max_value = 0
    total_visits = 0

    for row in rows:
        weekday_idx = row.get("weekday_idx")
        hour_idx = row.get("hour_idx")
        visits_count = int(row.get("visits_count") or 0)

        if weekday_idx is None or hour_idx is None:
            continue

        weekday_idx = int(weekday_idx)
        hour_idx = int(hour_idx)

        if 0 <= weekday_idx <= 6 and 0 <= hour_idx <= 23:
            values[(weekday_idx, hour_idx)] = visits_count
            total_visits += visits_count
            max_value = max(max_value, visits_count)

    grid = []
    peak = {"day": "—", "hour": "—", "value": 0}

    for day in days:
        row_cells = []
        for hour in hours:
            value = values[(day["index"], hour)]
            if max_value <= 0 or value <= 0:
                level = 0
            else:
                level = max(1, min(5, round((value / max_value) * 5)))

            if value > peak["value"]:
                peak = {"day": day["full"], "hour": f"{hour:02d}:00", "value": value}

            row_cells.append({"hour": hour, "value": value, "level": level})

        grid.append({"day": day, "cells": row_cells})

    return {
        "period_days": period_days,
        "hours": hours,
        "days": days,
        "grid": grid,
        "max_value": max_value,
        "total_visits": total_visits,
        "peak": peak,
        "debug": {
            "current_start": str(current_start),
            "current_end": str(current_end),
        },
    }
