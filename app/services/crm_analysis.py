from __future__ import annotations

from typing import Any, Dict, List

from app.services.mailing import build_where_clause


def _round(value: Any, digits: int = 1) -> float:
    if value is None:
        return 0
    return round(float(value or 0), digits)


def _format_minutes(value: Any) -> str:
    minutes = int(round(float(value or 0)))
    if minutes <= 0:
        return "0 мин"
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} ч {rest} мин"
    if hours:
        return f"{hours} ч"
    return f"{rest} мин"


def _format_percent(value: Any) -> str:
    return f"{_round(float(value or 0) * 100, 1)}%"


def _empty_analysis() -> dict:
    return {
        "audience": {"total": 0, "telegram": 0, "telegram_percent": 0},
        "funnel": [],
        "funnel_period_label": "за всё время",
        "metrics": [],
    }


def _infer_funnel_period_days(rules: List[Dict[str, Any]]) -> int | None:
    period_by_field = {
        "visits_7d": 7,
        "sessions_7d": 7,
        "visits_30d": 30,
        "sessions_30d": 30,
        "visits_90d": 90,
        "sessions_90d": 90,
    }
    periods = [
        period_by_field[rule.get("field")]
        for rule in rules
        if rule.get("field") in period_by_field
    ]
    if not periods:
        return None
    return min(periods)


def get_crm_cohort_analysis(conn, club_id: int, rules: List[Dict[str, Any]]) -> dict:
    where_sql, params = build_where_clause(club_id, rules, require_telegram=False)
    funnel_period_days = _infer_funnel_period_days(rules)
    funnel_period_sql = ""
    funnel_params = list(params)
    if funnel_period_days:
        funnel_period_sql = "AND gs.date_start >= DATE_SUB(NOW(), INTERVAL %s DAY)"
        funnel_params.append(funnel_period_days)

    metrics_sql = f"""
        WITH filtered AS (
            SELECT
                up.club_id,
                up.guest_id,
                up.avg_session_minutes,
                up.avg_visits_per_month,
                up.night_share,
                up.weekend_share,
                g.telegram_id
            FROM user_portrait up
            JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
            {where_sql}
        )
        SELECT
            COUNT(*) AS total_guests,
            SUM(CASE WHEN telegram_id IS NOT NULL THEN 1 ELSE 0 END) AS telegram_guests,
            COALESCE(AVG(avg_session_minutes), 0) AS avg_session_minutes,
            COALESCE(AVG(avg_visits_per_month), 0) AS avg_visits_per_month,
            COALESCE(AVG(night_share), 0) AS night_share,
            COALESCE(AVG(weekend_share), 0) AS weekend_share,
            (
                SELECT COALESCE(AVG(gbt.amount), 0)
                FROM guest_balance_topups gbt
                JOIN filtered f ON f.club_id = gbt.club_id AND f.guest_id = gbt.guest_id
                WHERE gbt.topup_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ) AS avg_topup
        FROM filtered
    """

    funnel_sql = f"""
        WITH filtered AS (
            SELECT up.club_id, up.guest_id
            FROM user_portrait up
            JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
            {where_sql}
        ),
        visit_days AS (
            SELECT DISTINCT
                gs.club_id,
                gs.guest_id,
                DATE(gs.date_start) AS visit_day
            FROM guest_sessions gs
            JOIN filtered f ON f.club_id = gs.club_id AND f.guest_id = gs.guest_id
            WHERE gs.date_start IS NOT NULL
              {funnel_period_sql}
        ),
        ranked AS (
            SELECT
                club_id,
                guest_id,
                visit_day,
                ROW_NUMBER() OVER (PARTITION BY club_id, guest_id ORDER BY visit_day) AS rn
            FROM visit_days
        ),
        per_guest AS (
            SELECT
                club_id,
                guest_id,
                MAX(CASE WHEN rn = 1 THEN visit_day END) AS visit_1,
                MAX(CASE WHEN rn = 2 THEN visit_day END) AS visit_2,
                MAX(CASE WHEN rn = 3 THEN visit_day END) AS visit_3,
                MAX(CASE WHEN rn = 4 THEN visit_day END) AS visit_4,
                MAX(CASE WHEN rn = 5 THEN visit_day END) AS visit_5,
                MAX(CASE WHEN rn = 6 THEN visit_day END) AS visit_6,
                MAX(CASE WHEN rn = 7 THEN visit_day END) AS visit_7
            FROM ranked
            WHERE rn <= 7
            GROUP BY club_id, guest_id
        )
        SELECT
            SUM(CASE WHEN visit_1 IS NOT NULL THEN 1 ELSE 0 END) AS step_1,
            SUM(CASE WHEN visit_2 IS NOT NULL THEN 1 ELSE 0 END) AS step_2,
            SUM(CASE WHEN visit_3 IS NOT NULL THEN 1 ELSE 0 END) AS step_3,
            SUM(CASE WHEN visit_4 IS NOT NULL THEN 1 ELSE 0 END) AS step_4,
            SUM(CASE WHEN visit_5 IS NOT NULL THEN 1 ELSE 0 END) AS step_5,
            SUM(CASE WHEN visit_6 IS NOT NULL THEN 1 ELSE 0 END) AS step_6,
            SUM(CASE WHEN visit_7 IS NOT NULL THEN 1 ELSE 0 END) AS step_7,
            AVG(CASE WHEN visit_1 IS NOT NULL AND visit_2 IS NOT NULL THEN DATEDIFF(visit_2, visit_1) END) AS gap_1_2,
            AVG(CASE WHEN visit_2 IS NOT NULL AND visit_3 IS NOT NULL THEN DATEDIFF(visit_3, visit_2) END) AS gap_2_3,
            AVG(CASE WHEN visit_3 IS NOT NULL AND visit_4 IS NOT NULL THEN DATEDIFF(visit_4, visit_3) END) AS gap_3_4,
            AVG(CASE WHEN visit_4 IS NOT NULL AND visit_5 IS NOT NULL THEN DATEDIFF(visit_5, visit_4) END) AS gap_4_5,
            AVG(CASE WHEN visit_5 IS NOT NULL AND visit_6 IS NOT NULL THEN DATEDIFF(visit_6, visit_5) END) AS gap_5_6,
            AVG(CASE WHEN visit_6 IS NOT NULL AND visit_7 IS NOT NULL THEN DATEDIFF(visit_7, visit_6) END) AS gap_6_7
        FROM per_guest
    """

    with conn.cursor() as cur:
        cur.execute(metrics_sql, params)
        metrics_row = cur.fetchone() or {}
        total_guests = int(metrics_row.get("total_guests") or 0)
        if total_guests <= 0:
            return _empty_analysis()

        cur.execute(funnel_sql, funnel_params)
        funnel_row = cur.fetchone() or {}

    telegram_guests = int(metrics_row.get("telegram_guests") or 0)
    max_step = max(int(funnel_row.get(f"step_{idx}") or 0) for idx in range(1, 8)) or 1
    funnel = []
    for idx in range(1, 8):
        count = int(funnel_row.get(f"step_{idx}") or 0)
        gap = funnel_row.get(f"gap_{idx}_{idx + 1}") if idx < 7 else None
        funnel.append(
            {
                "step": idx,
                "label": f"{idx} визит",
                "count": count,
                "height": max(8, round(count / max_step * 100)),
                "gap_to_next": _round(gap, 1) if gap is not None else None,
            }
        )

    night_share = float(metrics_row.get("night_share") or 0)
    weekend_share = float(metrics_row.get("weekend_share") or 0)

    return {
        "audience": {
            "total": total_guests,
            "telegram": telegram_guests,
            "telegram_percent": _round(telegram_guests / total_guests * 100, 1),
        },
        "funnel": funnel,
        "funnel_period_label": f"за последние {funnel_period_days} дней" if funnel_period_days else "за всё время",
        "metrics": [
            {"label": "Среднее пополнение", "value": f"{int(round(float(metrics_row.get('avg_topup') or 0)))} ₽", "hint": "По пополнениям за последние 30 дней"},
            {"label": "Средняя длина сессии", "value": _format_minutes(metrics_row.get("avg_session_minutes")), "hint": "Среднее по гостям когорты"},
            {"label": "Сессий в месяц", "value": str(_round(metrics_row.get("avg_visits_per_month"), 1)), "hint": "Среднее число сессий на гостя"},
            {"label": "Ночь / день", "value": f"{_format_percent(night_share)} / {_format_percent(1 - night_share)}", "hint": "Доля ночных и дневных визитов"},
            {"label": "Выходные / будни", "value": f"{_format_percent(weekend_share)} / {_format_percent(1 - weekend_share)}", "hint": "Доля визитов по дням недели"},
        ],
    }
