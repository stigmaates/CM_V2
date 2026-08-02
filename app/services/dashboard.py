from collections import defaultdict
from datetime import datetime, timedelta

from app.core import calc_percent_change, get_db_connection, get_period_range
from app.services.missions import (
    get_club_missions,
    _day_overlap_hours,
    _max_consecutive_day_streak,
    _night_overlap_hours,
)


def _round_display(value):
    """Округляет значения для отображения на дашборде без дробной части."""
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0




def _sparkline_path(values, width: int = 140, height: int = 56, padding: int = 6) -> str:
    """Build compact SVG path for KPI sparklines from real dashboard data."""
    clean_values = []
    for value in values or []:
        try:
            clean_values.append(float(value or 0))
        except (TypeError, ValueError):
            clean_values.append(0.0)

    if not clean_values:
        clean_values = [0.0]
    if len(clean_values) == 1:
        clean_values = [clean_values[0], clean_values[0]]

    min_value = min(clean_values)
    max_value = max(clean_values)
    value_range = max(max_value - min_value, 1)
    inner_w = max(width - padding * 2, 1)
    inner_h = max(height - padding * 2, 1)
    step_x = inner_w / (len(clean_values) - 1)

    points = []
    for index, value in enumerate(clean_values):
        x = padding + step_x * index
        y = padding + inner_h - ((value - min_value) / value_range) * inner_h
        points.append((round(x, 2), round(y, 2)))

    # Polyline path is intentionally simple and robust for any number of points.
    return "M " + " L ".join(f"{x} {y}" for x, y in points)


def _date_labels_for_period(current_start, current_end):
    labels = []
    current_day = current_start.date()
    last_day = current_end.date()
    while current_day <= last_day:
        labels.append(current_day)
        current_day += timedelta(days=1)
    return labels


def _build_kpi_sparklines(cursor, club_id: int, current_start, current_end) -> dict:
    labels = _date_labels_for_period(current_start, current_end)
    guests_map = {label: 0 for label in labels}
    retention_map = {label: 0 for label in labels}
    avg_check_map = {label: 0 for label in labels}

    cursor.execute(
        """
        SELECT DATE(date_start) AS d, COUNT(DISTINCT guest_id) AS cnt
        FROM guest_sessions
        WHERE club_id = %s
          AND date_start >= %s
          AND date_start < %s
        GROUP BY DATE(date_start)
        """,
        (club_id, current_start, current_end),
    )
    for row in cursor.fetchall() or []:
        if row.get("d") in guests_map:
            guests_map[row["d"]] = int(row.get("cnt") or 0)

    cursor.execute(
        """
        SELECT
            DATE(gs.date_start) AS d,
            COUNT(DISTINCT gs.guest_id) AS total_guests,
            COUNT(DISTINCT CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM guest_sessions prev
                    WHERE prev.club_id = gs.club_id
                      AND prev.guest_id = gs.guest_id
                      AND prev.date_start >= %s
                      AND prev.date_start < gs.date_start
                    LIMIT 1
                ) THEN gs.guest_id
            END) AS returned_guests
        FROM guest_sessions gs
        WHERE gs.club_id = %s
          AND gs.date_start >= %s
          AND gs.date_start < %s
        GROUP BY DATE(gs.date_start)
        """,
        (current_start, club_id, current_start, current_end),
    )
    for row in cursor.fetchall() or []:
        d = row.get("d")
        if d in retention_map:
            total = int(row.get("total_guests") or 0)
            returned = int(row.get("returned_guests") or 0)
            retention_map[d] = round((returned / total) * 100, 1) if total else 0

    cursor.execute(
        """
        SELECT DATE(topup_at) AS d, COALESCE(AVG(amount), 0) AS avg_check
        FROM guest_balance_topups
        WHERE club_id = %s
          AND topup_at >= %s
          AND topup_at < %s
        GROUP BY DATE(topup_at)
        """,
        (club_id, current_start, current_end),
    )
    for row in cursor.fetchall() or []:
        if row.get("d") in avg_check_map:
            avg_check_map[row["d"]] = float(row.get("avg_check") or 0)

    guests_values = [guests_map[label] for label in labels]
    retention_values = [retention_map[label] for label in labels]
    avg_check_values = [avg_check_map[label] for label in labels]

    return {
        "guests_values": guests_values,
        "retention_values": retention_values,
        "avg_check_values": avg_check_values,
        "guests_path": _sparkline_path(guests_values),
        "retention_path": _sparkline_path(retention_values),
        "avg_check_path": _sparkline_path(avg_check_values),
    }


def _visit_days_label(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день"
    if days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        return f"{days} дня"
    return f"{days} дней"


def _get_visit_streak_funnel(cursor, club_id: int, current_start, current_end) -> list[dict]:
    """Return cumulative visit-day funnel for selected period: 1 day, 2+ days ... 7+ days."""
    cursor.execute(
        """
        SELECT guest_id, COUNT(DISTINCT DATE(date_start)) AS visit_days
        FROM guest_sessions
        WHERE club_id = %s
          AND date_start >= %s
          AND date_start < %s
        GROUP BY guest_id
        HAVING visit_days > 0
        """,
        (club_id, current_start, current_end),
    )
    rows = cursor.fetchall() or []
    visit_days_by_guest = [int(row.get("visit_days") or 0) for row in rows]
    if not visit_days_by_guest:
        return []

    max_level = 7
    counts = {
        level: sum(1 for visit_days in visit_days_by_guest if visit_days >= level)
        for level in range(1, max_level + 1)
    }
    max_count = max(counts.values(), default=1) or 1

    def label_for_level(level: int) -> str:
        if level == 1:
            return "1 день"
        return f"{level}+ дней"

    return [
        {
            "days": level,
            "label": label_for_level(level),
            "short_label": "1" if level == 1 else f"{level}+",
            "count": counts[level],
            "height": max(8, _round_display((counts[level] / max_count) * 100)) if counts[level] else 0,
        }
        for level in range(1, max_level + 1)
    ]


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



def get_case_openings_chart(club_id: int, period_days: int = 30) -> dict:
    """Return case opening counts for the selected dashboard period."""
    if not club_id:
        return {"items": [], "total_openings": 0, "unique_openers": 0, "period_days": period_days}

    period_days = period_days if period_days in (7, 30, 90) else 30
    current_end = datetime.now()
    current_start = current_end - timedelta(days=period_days)

    conn = get_db_connection()
    unique_openers = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id AS case_id,
                    c.name AS case_name,
                    c.image_url AS case_image_url,
                    c.sort_order,
                    COUNT(o.id) AS openings_count
                FROM club_cases c
                LEFT JOIN guest_case_openings o
                  ON o.club_id = c.club_id
                 AND o.case_id = c.id
                 AND o.created_at >= %s
                 AND o.created_at < %s
                WHERE c.club_id = %s
                GROUP BY c.id, c.name, c.image_url, c.sort_order
                ORDER BY openings_count DESC, c.sort_order ASC, c.id ASC
                """,
                (current_start, current_end, club_id),
            )
            rows = cursor.fetchall() or []

            cursor.execute(
                """
                SELECT COUNT(DISTINCT guest_id) AS unique_openers
                FROM guest_case_openings
                WHERE club_id = %s
                  AND created_at >= %s
                  AND created_at < %s
                """,
                (club_id, current_start, current_end),
            )
            unique_row = cursor.fetchone() or {}
            unique_openers = int(unique_row.get("unique_openers") or 0)

            cursor.execute(
                """
                SELECT
                    i.case_id,
                    i.id AS item_id,
                    i.name AS item_name,
                    i.rarity_label,
                    i.probability,
                    COUNT(o.id) AS drops_count
                FROM club_case_items i
                LEFT JOIN guest_case_openings o
                  ON o.item_id = i.id
                 AND o.club_id = i.club_id
                 AND o.case_id = i.case_id
                 AND o.created_at >= %s
                 AND o.created_at < %s
                WHERE i.club_id = %s
                  AND (i.is_active = 1 OR o.id IS NOT NULL)
                GROUP BY i.case_id, i.id, i.name, i.rarity_label, i.probability, i.sort_order
                ORDER BY i.case_id ASC, drops_count DESC, i.sort_order ASC, i.id ASC
                """,
                (current_start, current_end, club_id),
            )
            prize_rows = cursor.fetchall() or []
    finally:
        conn.close()

    prize_rows_by_case = defaultdict(list)
    for prize_row in prize_rows:
        prize_rows_by_case[int(prize_row.get("case_id") or 0)].append(prize_row)

    max_openings = max((int(row.get("openings_count") or 0) for row in rows), default=0)
    items = []
    for row in rows:
        case_id = int(row.get("case_id") or 0)
        openings = int(row.get("openings_count") or 0)
        width = round((openings / max_openings) * 100, 1) if max_openings else 0
        prize_drops = []
        for prize_row in prize_rows_by_case.get(case_id, []):
            drops = int(prize_row.get("drops_count") or 0)
            prize_drops.append(
                {
                    "item_id": int(prize_row.get("item_id") or 0),
                    "name": prize_row.get("item_name") or "Без названия",
                    "rarity": prize_row.get("rarity_label") or "Обычный",
                    "drops": drops,
                    "percent": round((drops / openings) * 100, 1) if openings else 0,
                    "configured_percent": round(float(prize_row.get("probability") or 0), 1),
                }
            )
        items.append(
            {
                "case_id": case_id,
                "name": row.get("case_name") or "Без названия",
                "image_url": row.get("case_image_url") or "",
                "openings": openings,
                "width": width,
                "prize_drops": prize_drops,
            }
        )

    return {
        "items": items,
        "total_openings": sum(item["openings"] for item in items),
        "unique_openers": unique_openers,
        "period_days": period_days,
    }


def get_mission_completions_chart(club_id: int, period_days: int = 30) -> dict:
    """Return completion counts by mission for the selected dashboard period."""
    if not club_id:
        return {"items": [], "total_completions": 0, "period_days": period_days}

    period_days = period_days if period_days in (7, 30, 90) else 30
    ranges = get_period_range(period_days)
    current_start = ranges["current_start"]
    current_end = ranges["current_end"]

    active_missions = get_club_missions(club_id)
    if not active_missions:
        return {"items": [], "total_completions": 0, "period_days": period_days}

    guest_ids = _get_guest_ids_for_engagement_scope(
        club_id,
        current_start=current_start,
        current_end=current_end,
        all_time=False,
    )
    sessions_by_guest = _get_sessions_by_guest(club_id, guest_ids)
    spins_by_guest = _get_wheel_spins_by_guest(club_id, guest_ids)

    completion_counts = defaultdict(int)
    completion_cache = {}

    for guest_id in guest_ids:
        guest_sessions = sessions_by_guest.get(guest_id, [])
        guest_spins = spins_by_guest.get(guest_id, [])

        for mission in active_missions:
            completed_at = _get_mission_completion_at_from_preloaded(
                guest_id,
                club_id,
                mission,
                guest_sessions,
                guest_spins,
                active_missions,
                completion_cache,
            )
            if completed_at and current_start <= completed_at < current_end:
                completion_counts[mission.get("id")] += 1

    max_completions = max(completion_counts.values(), default=0)
    items = []
    for mission in active_missions:
        mission_id = mission.get("id")
        completions = int(completion_counts.get(mission_id, 0))
        width = round((completions / max_completions) * 100, 1) if max_completions else 0
        items.append(
            {
                "mission_id": int(mission_id or 0),
                "name": mission.get("display_name") or mission.get("name") or "Без названия",
                "completions": completions,
                "width": width,
            }
        )

    items.sort(key=lambda item: (-item["completions"], item["name"]))

    return {
        "items": items,
        "total_completions": sum(item["completions"] for item in items),
        "period_days": period_days,
    }

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
                       COALESCE(SUM(amount), 0) AS total_sum,
                       COALESCE(AVG(amount), 0) AS avg_check
                FROM guest_balance_topups
                WHERE club_id = %s
                  AND topup_at >= %s
                  AND topup_at < %s
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
                       COALESCE(SUM(amount), 0) AS total_sum,
                       COALESCE(AVG(amount), 0) AS avg_check
                FROM guest_balance_topups
                WHERE club_id = %s
                  AND topup_at >= %s
                  AND topup_at < %s
                """,
                (club_id, previous_start, previous_end),
            )
            avg_check_previous_row = cursor.fetchone()

            operations_count_previous = avg_check_previous_row["operations_count"] or 0
            total_sum_previous = float(avg_check_previous_row["total_sum"] or 0)
            avg_check_previous = float(avg_check_previous_row["avg_check"] or 0)

            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM guests
                WHERE club_id = %s
                  AND COALESCE(date_insert, created_at) >= %s
                  AND COALESCE(date_insert, created_at) < %s
                """,
                (club_id, current_start, current_end),
            )
            total_guests = cursor.fetchone()["cnt"] or 0

            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM guests
                WHERE club_id = %s
                  AND COALESCE(date_insert, created_at) >= %s
                  AND COALESCE(date_insert, created_at) < %s
                  AND telegram_id IS NOT NULL
                  AND TRIM(CAST(telegram_id AS CHAR)) <> ''
                """,
                (club_id, current_start, current_end),
            )
            guests_with_telegram = cursor.fetchone()["cnt"] or 0

            csi_percent = _round_display((guests_with_telegram / total_guests) * 100) if total_guests > 0 else 0

            # Карточка «Людей в рассылке» должна показывать всю доступную Telegram-базу клуба,
            # а не только новых гостей за выбранный период. ER выше остается периодной метрикой.
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
            mailing_count = cursor.fetchone()["cnt"] or 0

            kpi_sparklines = _build_kpi_sparklines(cursor, club_id, current_start, current_end)
            visit_streak_funnel = _get_visit_streak_funnel(cursor, club_id, current_start, current_end)

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
            "kpi_sparklines": kpi_sparklines,
            "visit_streak_funnel": visit_streak_funnel,
            "chart": chart_data,
            "debug": {
                "club_id": club_id,
                "current_start": str(current_start),
                "current_end": str(current_end),
                "previous_start": str(previous_start),
                "previous_end": str(previous_end),
            },
        }
        return result
    finally:
        conn.close()



def get_first_visit_feedback_stats(club_id: int, period_days: int = 30) -> dict:
    """Analytics for first-visit survey responses within selected period."""
    now = datetime.now()
    current_end = now
    current_start = now - timedelta(days=period_days)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            from app.services.first_visit_survey import ensure_first_visit_survey_tables
            ensure_first_visit_survey_tables(cursor)
            cursor.execute(
                """
                SELECT
                    guest_id,
                    rating,
                    feedback_text,
                    COALESCE(completed_at, updated_at, created_at) AS feedback_at
                FROM first_visit_surveys
                WHERE club_id = %s
                  AND status = 'completed'
                  AND rating IS NOT NULL
                  AND COALESCE(completed_at, updated_at, created_at) >= %s
                  AND COALESCE(completed_at, updated_at, created_at) < %s
                ORDER BY feedback_at DESC, id DESC
                """,
                (club_id, current_start, current_end),
            )
            rows = cursor.fetchall() or []

        def normalize_text(value):
            return ' '.join(str(value or '').split())

        total_responses = len(rows)
        avg_rating = 0.0
        if total_responses:
            avg_rating = round(sum(float(row.get('rating') or 0) for row in rows) / total_responses, 1)

        positive_messages = []
        negative_messages = []
        for row in rows:
            feedback_text = normalize_text(row.get('feedback_text'))
            if not feedback_text:
                continue
            item = {
                'guest_id': row.get('guest_id'),
                'rating': int(row.get('rating') or 0),
                'text': feedback_text,
                'short_text': feedback_text[:140] + ('…' if len(feedback_text) > 140 else ''),
                'date': row.get('feedback_at').strftime('%d.%m.%Y %H:%M') if row.get('feedback_at') else '',
            }
            if item['rating'] >= 4:
                positive_messages.append(item)
            else:
                negative_messages.append(item)

        return {
            'avg_rating': avg_rating,
            'avg_rating_display': str(avg_rating).replace('.', ','),
            'total_responses': total_responses,
            'positive_count': len(positive_messages),
            'negative_count': len(negative_messages),
            'positive_preview': positive_messages[:3],
            'negative_preview': negative_messages[:3],
            'positive_messages': positive_messages,
            'negative_messages': negative_messages,
            'period_days': period_days,
        }
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


def _get_guest_ids_for_engagement_scope(club_id: int, current_start=None, current_end=None, all_time: bool = False):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if all_time:
                cursor.execute(
                    """
                    SELECT guest_id
                    FROM guests
                    WHERE club_id = %s
                    """,
                    (club_id,),
                )
            else:
                # Для плашки вовлеченности период должен включать не только новых
                # зарегистрированных гостей, но и гостей, которые реально были
                # активны в выбранном периоде. Иначе задания/колесо могли
                # показывать 0, если гости зарегистрированы давно, но выполняли
                # активности сейчас.
                cursor.execute(
                    """
                    SELECT DISTINCT guest_id
                    FROM (
                        SELECT guest_id
                        FROM guests
                        WHERE club_id = %s
                          AND COALESCE(date_insert, created_at) >= %s
                          AND COALESCE(date_insert, created_at) < %s

                        UNION

                        SELECT guest_id
                        FROM guest_sessions
                        WHERE club_id = %s
                          AND date_start >= %s
                          AND date_start < %s

                        UNION

                        SELECT guest_id
                        FROM guest_wheel_spins
                        WHERE club_id = %s
                          AND created_at >= %s
                          AND created_at < %s

                        UNION

                        SELECT guest_id
                        FROM guest_case_openings
                        WHERE club_id = %s
                          AND created_at >= %s
                          AND created_at < %s
                    ) scope_guests
                    """,
                    (
                        club_id, current_start, current_end,
                        club_id, current_start, current_end,
                        club_id, current_start, current_end,
                        club_id, current_start, current_end,
                    ),
                )
            rows = cursor.fetchall() or []
            return [row["guest_id"] for row in rows]
    finally:
        conn.close()


def _build_guest_filter_sql(guest_ids):
    if not guest_ids:
        return " AND 1 = 0", []
    placeholders = ",".join(["%s"] * len(guest_ids))
    return f" AND guest_id IN ({placeholders})", list(guest_ids)


def _get_sessions_by_guest(club_id: int, guest_ids=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guest_filter_sql, guest_filter_params = _build_guest_filter_sql(guest_ids)
            cursor.execute(
                f"""
                SELECT guest_id, date_start, date_stop
                FROM guest_sessions
                WHERE club_id = %s
                  AND date_start IS NOT NULL
                  {guest_filter_sql}
                ORDER BY guest_id, date_start
                """,
                [club_id] + guest_filter_params,
            )
            rows = cursor.fetchall()

        sessions_by_guest = defaultdict(list)
        for row in rows:
            sessions_by_guest[row["guest_id"]].append(row)

        return sessions_by_guest
    finally:
        conn.close()


def _get_first_spin_by_guest(club_id: int, guest_ids=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guest_filter_sql, guest_filter_params = _build_guest_filter_sql(guest_ids)
            cursor.execute(
                f"""
                SELECT guest_id, MIN(created_at) AS first_spin_at
                FROM guest_wheel_spins
                WHERE club_id = %s
                  {guest_filter_sql}
                GROUP BY guest_id
                """,
                [club_id] + guest_filter_params,
            )
            rows = cursor.fetchall()

        return {
            row["guest_id"]: row["first_spin_at"]
            for row in rows
            if row["first_spin_at"] is not None
        }
    finally:
        conn.close()


# Backward-compatible wrappers used by older code paths.
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



def _get_min_hours_from_mission(mission) -> int:
    config = mission.get("config") or {}
    if isinstance(config, dict):
        try:
            return int(config.get("min_hours", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _session_duration_hours(session_row) -> float:
    date_start = session_row.get("date_start")
    date_stop = session_row.get("date_stop")
    if not date_start or not date_stop or date_stop <= date_start:
        return 0.0
    return (date_stop - date_start).total_seconds() / 3600


def _session_allowed_by_mission_period(session_row, mission) -> bool:
    date_start = session_row.get("date_start")
    if not date_start:
        return False

    mission_start = mission.get("start_at")
    mission_end = mission.get("end_at")

    if mission_start and date_start < mission_start:
        return False
    if mission_end and date_start > mission_end:
        return False
    return True


def _event_allowed_by_mission_period(event_at, mission) -> bool:
    if not event_at:
        return False

    mission_start = mission.get("start_at")
    mission_end = mission.get("end_at")

    if mission_start and event_at < mission_start:
        return False
    if mission_end and event_at > mission_end:
        return False
    return True


def _mission_matching_session_dates(guest_sessions, mission) -> list:
    """Return dates of session-based mission units that count toward target."""
    metric = mission.get("target_metric")
    min_hours = _get_min_hours_from_mission(mission)
    matched_dates = []

    for session_row in guest_sessions:
        if not _session_allowed_by_mission_period(session_row, mission):
            continue

        date_start = session_row.get("date_start")
        if not date_start:
            continue

        duration_hours = _session_duration_hours(session_row)

        if metric == "visits_count":
            matched_dates.append(date_start)
        elif metric == "night_visits_count" and (date_start.hour >= 22 or date_start.hour < 8):
            matched_dates.append(date_start)
        elif metric == "weekend_visits_count" and date_start.isoweekday() in (6, 7):
            matched_dates.append(date_start)
        elif metric in ("long_visits_count", "visits_min_hours_count") and duration_hours >= min_hours:
            matched_dates.append(date_start)
        elif metric == "weekday_visits_min_hours_count" and date_start.weekday() <= 4 and duration_hours >= min_hours:
            matched_dates.append(date_start)
        elif metric == "weekend_visits_min_hours_count" and date_start.weekday() in (5, 6) and duration_hours >= min_hours:
            matched_dates.append(date_start)

    return sorted(matched_dates)


def _get_wheel_spins_by_guest(club_id: int, guest_ids=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guest_filter_sql, guest_filter_params = _build_guest_filter_sql(guest_ids)
            cursor.execute(
                f"""
                SELECT guest_id, created_at
                FROM guest_wheel_spins
                WHERE club_id = %s
                  AND created_at IS NOT NULL
                  {guest_filter_sql}
                ORDER BY guest_id, created_at
                """,
                [club_id] + guest_filter_params,
            )
            rows = cursor.fetchall() or []

        spins_by_guest = defaultdict(list)
        for row in rows:
            spins_by_guest[row["guest_id"]].append(row["created_at"])
        return spins_by_guest
    finally:
        conn.close()

def _get_case_openings_by_guest(club_id: int, guest_ids=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guest_filter_sql, guest_filter_params = _build_guest_filter_sql(guest_ids)
            cursor.execute(
                f"""
                SELECT guest_id, created_at
                FROM guest_case_openings
                WHERE club_id = %s
                  AND created_at IS NOT NULL
                  {guest_filter_sql}
                ORDER BY guest_id, created_at
                """,
                [club_id] + guest_filter_params,
            )
            rows = cursor.fetchall() or []

        openings_by_guest = defaultdict(list)
        for row in rows:
            openings_by_guest[row["guest_id"]].append(row["created_at"])
        return openings_by_guest
    finally:
        conn.close()



def _get_mission_completion_at_from_preloaded(
    guest_id,
    club_id,
    mission,
    guest_sessions,
    guest_spins,
    active_missions,
    completion_cache,
    stack=None,
):
    """
    Calculate mission completion date for owner dashboard using the same mission metrics
    as guest dashboard, but on preloaded sessions/spins to avoid mixing clubs and to
    support all current mission types.
    """
    target = int(mission.get("target_amount") or 0)
    if target <= 0:
        return None

    mission_id = mission.get("id")
    cache_key = (guest_id, mission_id)
    if cache_key in completion_cache:
        return completion_cache[cache_key]

    stack = set(stack or set())
    if mission_id in stack:
        return None
    stack.add(mission_id)

    metric = mission.get("target_metric")
    completed_at = None

    # Count-based session missions.
    if metric in {
        "visits_count",
        "night_visits_count",
        "weekend_visits_count",
        "long_visits_count",
        "visits_min_hours_count",
        "weekday_visits_min_hours_count",
        "weekend_visits_min_hours_count",
    }:
        matched_dates = _mission_matching_session_dates(guest_sessions, mission)
        if len(matched_dates) >= target:
            completed_at = matched_dates[target - 1]

    # Total hours missions.
    elif metric in {"total_hours", "night_hours_total", "day_hours_total"}:
        total_hours = 0.0
        for session_row in sorted(guest_sessions, key=lambda row: row.get("date_start")):
            if not _session_allowed_by_mission_period(session_row, mission):
                continue
            date_start = session_row.get("date_start")
            date_stop = session_row.get("date_stop")
            if not date_start or not date_stop:
                continue

            if metric == "total_hours":
                total_hours += _session_duration_hours(session_row)
            elif metric == "night_hours_total":
                total_hours += _night_overlap_hours(date_start, date_stop)
            elif metric == "day_hours_total":
                total_hours += _day_overlap_hours(date_start, date_stop)

            if int(total_hours) >= target:
                completed_at = date_start
                break

    # Consecutive visit days.
    elif metric == "consecutive_days_count":
        sorted_sessions = sorted(
            [row for row in guest_sessions if _session_allowed_by_mission_period(row, mission)],
            key=lambda row: row.get("date_start"),
        )
        days_seen = []
        for session_row in sorted_sessions:
            date_start = session_row.get("date_start")
            if not date_start:
                continue
            days_seen.append(date_start.date())
            if _max_consecutive_day_streak(days_seen) >= target:
                completed_at = date_start
                break

    # Wheel spins.
    elif metric == "wheel_spins_count":
        spin_dates = sorted(
            spin_at for spin_at in guest_spins
            if _event_allowed_by_mission_period(spin_at, mission)
        )
        if len(spin_dates) >= target:
            completed_at = spin_dates[target - 1]

    # Meta-mission: complete N other missions.
    elif metric == "completed_missions_count":
        other_completion_dates = []
        for other_mission in active_missions:
            if other_mission.get("id") == mission_id:
                continue
            if other_mission.get("target_metric") == "completed_missions_count":
                continue
            other_completed_at = _get_mission_completion_at_from_preloaded(
                guest_id,
                club_id,
                other_mission,
                guest_sessions,
                guest_spins,
                active_missions,
                completion_cache,
                stack=stack,
            )
            if other_completed_at:
                other_completion_dates.append(other_completed_at)

        other_completion_dates.sort()
        if len(other_completion_dates) >= target:
            completed_at = other_completion_dates[target - 1]

    completion_cache[cache_key] = completed_at
    return completed_at


def get_dashboard_engagement_stats(club_id: int, period_days: int = 30, all_time: bool = False):
    ranges = get_period_range(period_days)
    current_start = ranges["current_start"]
    current_end = ranges["current_end"]

    guest_ids = _get_guest_ids_for_engagement_scope(
        club_id,
        current_start=current_start,
        current_end=current_end,
        all_time=all_time,
    )
    total_guests = len(guest_ids)
    sessions_by_guest = _get_sessions_by_guest(club_id, guest_ids)
    spins_by_guest = _get_wheel_spins_by_guest(club_id, guest_ids)
    case_openings_by_guest = _get_case_openings_by_guest(club_id, guest_ids)

    # -------------------------
    # WHEEL
    # -------------------------
    first_spin_by_guest = {
        guest_id: min(spin_dates)
        for guest_id, spin_dates in spins_by_guest.items()
        if spin_dates
    }

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
    # CASES
    # -------------------------
    first_case_opening_by_guest = {
        guest_id: min(opening_dates)
        for guest_id, opening_dates in case_openings_by_guest.items()
        if opening_dates
    }

    case_opened_guests = len(first_case_opening_by_guest)
    case_returned_guests = 0

    for guest_id, first_case_opened_at in first_case_opening_by_guest.items():
        guest_sessions = sessions_by_guest.get(guest_id, [])
        returned = any(
            session_row["date_start"] and session_row["date_start"] > first_case_opened_at
            for session_row in guest_sessions
        )
        if returned:
            case_returned_guests += 1

    case_engagement_percent = _round_display((case_opened_guests / total_guests) * 100) if total_guests > 0 else 0

    # -------------------------
    # MISSIONS
    # -------------------------
    active_missions = get_club_missions(club_id)

    mission_completed_guests = 0
    mission_returned_guests = 0

    completion_cache = {}

    for guest_id in guest_ids:
        guest_sessions = sessions_by_guest.get(guest_id, [])
        guest_spins = spins_by_guest.get(guest_id, [])
        completion_dates = []

        for mission in active_missions:
            completion_at = _get_mission_completion_at_from_preloaded(
                guest_id,
                club_id,
                mission,
                guest_sessions,
                guest_spins,
                active_missions,
                completion_cache,
            )
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
        "scope": "all_time" if all_time else "period",
        "period_days": period_days,
        "wheel": {
            "total_guests": total_guests,
            "involved_guests": wheel_spun_guests,
            "engagement_percent": wheel_engagement_percent,
            "returned_guests": wheel_returned_guests,
        },
        "cases": {
            "total_guests": total_guests,
            "involved_guests": case_opened_guests,
            "engagement_percent": case_engagement_percent,
            "returned_guests": case_returned_guests,
        },
        "missions": {
            "total_guests": total_guests,
            "involved_guests": mission_completed_guests,
            "engagement_percent": mission_engagement_percent,
            "returned_guests": mission_returned_guests,
        },
    }


def get_dashboard_audience_stats(club_id: int, telegram_only: bool = False) -> dict:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            where_sql = "WHERE club_id = %s"
            params = [club_id]
            if telegram_only:
                # user_portrait пересобирается из guests.telegram_id и хранит признак has_telegram.
                # Так фильтр совпадает с CRM-сегментами и не зависит от выбранного периода heatmap.
                where_sql += " AND COALESCE(has_telegram, 0) = 1"

            cursor.execute(
                f"""
                SELECT
                    crm_type,
                    COUNT(*) AS cnt,
                    SUM(CASE WHEN COALESCE(has_telegram, 0) = 1 THEN 1 ELSE 0 END) AS telegram_cnt
                FROM user_portrait
                {where_sql}
                GROUP BY crm_type
                """,
                tuple(params),
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
            "top_telegram": 0,
            "base_telegram": 0,
            "rare_telegram": 0,
            "risk_telegram": 0,
            "lost_telegram": 0,
            "dead_telegram": 0,
            "no_visits_telegram": 0,
            "total_telegram": 0,
            "telegram_only": bool(telegram_only),
        }

        for row in rows:
            crm_type = row["crm_type"]
            cnt = int(row["cnt"] or 0)
            telegram_cnt = int(row.get("telegram_cnt") or 0)

            if crm_type in audience:
                audience[crm_type] = cnt
                audience[f"{crm_type}_telegram"] = telegram_cnt
                audience["total"] += cnt
                audience["total_telegram"] += telegram_cnt

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
