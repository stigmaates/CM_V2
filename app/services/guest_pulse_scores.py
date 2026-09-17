"""Deterministic H/V/E calculations. Inputs are normalized visits, never SQL sessions."""

from bisect import bisect_left
from datetime import timedelta
from statistics import mean, median, pstdev

# Versioned product rules, independent of UI. Per-deployment overrides live in config.
from app.config import GUEST_PULSE_CONFIG

AUDIENCES = (
    ("new", "Новые / формируют привычку", "#60a5fa"),
    ("churned", "Потерянные", "#64748b"),
    ("valuable_risk", "Ценные в зоне риска", "#f97316"),
    ("low_engagement", "Активные, но не вовлечены", "#a78bfa"),
    ("loyal", "Лояльное ядро", "#34d399"),
    ("risk", "В зоне риска", "#fb7185"),
    ("other", "Остальные", "#94a3b8"),
)
LIFECYCLE_LABELS = {
    "NEW": "Новый",
    "ACTIVATING": "Формирует привычку",
    "ACTIVE": "Активный",
    "AT_RISK": "В зоне риска",
    "HIGH_RISK": "Высокий риск",
    "CHURNED": "Потерянный",
    "REACTIVATED": "Вернулся",
    "INSUFFICIENT_DATA": "Недостаточно данных",
}
SEGMENTS = {
    "high_value_at_risk": "Ценные в зоне риска",
    "strong_decline": "Резко начали выпадать",
    "active_high_value": "Активные ценные",
    "active_low_engagement": "Активные, но не вовлечены",
    "high_risk": "Высокий риск",
    "reactivated": "Вернулись",
    "new": "Новые",
    "activating": "Формируют привычку",
}


def weighted(parts):
    available = [(v, w) for v, w in parts if v is not None]
    return round(sum(v * w for v, w in available) / sum(w for _, w in available), 2) if available else None


def upper_score(value, bands):
    return next(score for limit, score in bands if value <= limit)


def lower_score(value, bands):
    return next(score for limit, score in bands if value >= limit)


def visit_features(visits, now, config=None):
    cfg = config or GUEST_PULSE_CONFIG
    visits = [v for v in visits if v["date_stop"] <= now]
    starts = [v["date_start"] for v in visits]
    recent = [v for v in visits if v["date_start"] >= now - timedelta(days=cfg["history_days"])]
    gaps = [(b["date_start"] - a["date_start"]).total_seconds() / 86400 for a, b in zip(recent, recent[1:])]
    gaps = [g for g in gaps if g > 0]
    typical = median(gaps) if len(gaps) >= 3 else mean(gaps) if gaps else None
    days = (now.date() - starts[-1].date()).days if starts else None
    features = {
        "visits_total": len(visits),
        "first_visit_date": starts[0] if starts else None,
        "last_visit_date": starts[-1] if starts else None,
        "days_since_last_visit": days,
        "age_days": (now.date() - starts[0].date()).days if starts else 0,
        "typical_gap_days": typical,
        "avg_gap_days": mean(gaps) if gaps else None,
        "gap_ratio": days / typical if typical else None,
        "gap_cv": pstdev(gaps) / mean(gaps) if len(gaps) >= 4 else None,
    }
    for period in (30, 60, 90):
        window = [v for v in visits if v["date_start"] >= now - timedelta(days=period)]
        features[f"visits_{period}d"] = len(window)
        features[f"played_hours_{period}d"] = sum(v["played_hours"] for v in window)
    return features


def health(features, config=None):
    cfg = config or GUEST_PULSE_CONFIG
    f = features
    recency = (
        upper_score(f["gap_ratio"], ((0.75, 100), (1, 90), (1.25, 75), (1.5, 60), (2, 40), (3, 20), (float("inf"), 0)))
        if f["gap_ratio"] is not None
        else None
    )
    previous60 = f["visits_90d"] - f["visits_30d"]
    frequency_ratio = f["visits_30d"] / (previous60 / 2) if f["age_days"] >= 45 and previous60 >= 2 else None
    frequency = (
        lower_score(frequency_ratio, ((1.1, 100), (0.9, 90), (0.75, 70), (0.5, 45), (0.25, 20), (0, 0)))
        if frequency_ratio is not None
        else None
    )
    previous30 = f["visits_60d"] - f["visits_30d"]
    hours_previous30 = f["played_hours_60d"] - f["played_hours_30d"]
    visits_change = (f["visits_30d"] - previous30) / max(previous30, 1)
    hours_change = (f["played_hours_30d"] - hours_previous30) / max(hours_previous30, 1)
    activity_change = 0.6 * visits_change + 0.4 * hours_change
    trend = (
        lower_score(activity_change, ((0.25, 100), (0.1, 90), (-0.1, 80), (-0.25, 60), (-0.5, 35), (-float("inf"), 10)))
        if f["age_days"] >= 60
        else None
    )
    consistency = (
        upper_score(f["gap_cv"], ((0.25, 100), (0.5, 80), (0.75, 60), (1, 40), (float("inf"), 20)))
        if f["gap_cv"] is not None
        else None
    )
    score = (
        weighted(((recency, 0.4), (frequency, 0.3), (trend, 0.2), (consistency, 0.1)))
        if f["visits_total"] >= 2
        else None
    )
    reasons = []
    if f["gap_ratio"] is not None and f["gap_ratio"] > 3:
        score = min(score, 25) if score is not None else None
    if f["visits_total"] >= 3 and f["days_since_last_visit"] >= cfg["churn_days"]:
        score = min(score, 15) if score is not None else 15
    if recency is not None and recency <= 40:
        reasons.append("RECENCY_WORSE")
    if frequency_ratio is not None and frequency_ratio < 0.9:
        reasons.append("FREQUENCY_DOWN")
    if trend is not None and activity_change < -0.1:
        if visits_change < 0:
            reasons.append("VISITS_DOWN")
        if hours_change < 0:
            reasons.append("HOURS_DOWN")
    if consistency is not None and consistency <= 40:
        reasons.append("LOW_CONSISTENCY")
    reason = reasons[0] if reasons else "INSUFFICIENT_DATA" if score is None else "STABLE_BEHAVIOUR"
    text = {
        "INSUFFICIENT_DATA": "Для оценки привычки нужно несколько завершённых визитов.",
        "STABLE_BEHAVIOUR": "Поведение соответствует обычной активности гостя.",
        "FREQUENCY_DOWN": f"Частота визитов снизилась на {round((1-(frequency_ratio or 0))*100)}%.",
        "VISITS_DOWN": f"Число визитов снизилось на {round(-visits_change*100)}%.",
        "HOURS_DOWN": f"Игровое время снизилось на {round(-hours_change*100)}%.",
        "LOW_CONSISTENCY": "Интервалы между визитами стали нерегулярными.",
    }
    if reason == "RECENCY_WORSE":
        text[reason] = (
            f"Обычно приходит каждые {f['typical_gap_days']:.1f} дн., последний визит — {f['days_since_last_visit']} дн. назад."
        )
    level = (
        lower_score(
            score,
            (
                (cfg["healthy_min"], "HEALTHY"),
                (cfg["stable_min"], "STABLE"),
                (cfg["at_risk_min"], "AT_RISK"),
                (cfg["high_risk_min"], "HIGH_RISK"),
                (0, "CHURNING"),
            ),
        )
        if score is not None
        else None
    )
    return {
        "score": score,
        "level": level,
        "recency": recency,
        "frequency": frequency,
        "trend": trend,
        "consistency": consistency,
        "frequency_ratio": frequency_ratio,
        "activity_change": activity_change,
        "reason_code": reason,
        "reason_codes": reasons,
        "reason_text": text[reason],
        "preliminary": 2 <= f["visits_total"] <= 3,
    }


def lifecycle(features, h, now, previous=None, config=None):
    cfg = config or GUEST_PULSE_CONFIG
    previous = previous or {}
    old = previous.get("lifecycle_status")
    last = features["last_visit_date"]
    reactivated_at = previous.get("reactivated_at")
    # A real new visit is required, not just the same visit seen by another job.
    if (
        old in ("CHURNED", "HIGH_RISK")
        and last
        and previous.get("last_visit_date")
        and last > previous["last_visit_date"]
        and last > previous["lifecycle_status_changed_at"]
    ):
        reactivated_at = last
    if reactivated_at and timedelta(0) <= now - reactivated_at < timedelta(days=14):
        status = "REACTIVATED"
    elif features["visits_total"] == 1:
        status = "NEW"
    elif 2 <= features["visits_total"] <= 3 and features["age_days"] <= 45:
        status = "ACTIVATING"
    elif features["visits_total"] >= 3 and (
        (features["gap_ratio"] or 0) > 3 or features["days_since_last_visit"] >= cfg["churn_days"]
    ):
        status = "CHURNED"
    elif h["score"] is None:
        status = "INSUFFICIENT_DATA"
    else:
        status = (
            "HIGH_RISK"
            if h["score"] < cfg["at_risk_min"]
            else "AT_RISK" if h["score"] < cfg["stable_min"] else "ACTIVE"
        )
    return {
        "lifecycle_status": status,
        "lifecycle_label": LIFECYCLE_LABELS[status],
        "lifecycle_status_changed_at": previous.get("lifecycle_status_changed_at", now) if status == old else now,
        "previous_lifecycle_status": previous.get("previous_lifecycle_status") if status == old else old,
        "reactivated_at": reactivated_at,
        "last_visit_date": last,
    }


def value_scores(rows, config=None):
    cfg = config or GUEST_PULSE_CONFIG
    keys = (("revenue_90d", 0.45), ("played_hours_90d", 0.30), ("visits_90d", 0.20), ("avg_check_90d", 0.05))
    reference = {k: sorted(r[k] for r in rows if r["visits_90d"] >= 2 and r[k] is not None) for k, _ in keys}
    result = {}
    for row in rows:
        parts = {
            k: (
                100 * bisect_left(reference[k], row[k]) / len(reference[k])
                if reference[k] and row[k] is not None
                else None
            )
            for k, _ in keys
        }
        score = weighted([(parts[k], w) for k, w in keys])
        result[row["guest_id"]] = {
            "score": score,
            "level": (
                None
                if score is None
                else "HIGH" if score >= cfg["high_value_min"] else "MEDIUM" if score >= 40 else "LOW"
            ),
            "percentiles": parts,
            "reference_count": len(reference["visits_90d"]),
        }
    return result


def engagement(events, telegram_connected, now):
    past = [e for e in events if e["at"] <= now]
    recent = [e for e in past if e["at"] >= now - timedelta(days=30)]
    missions = sum(e["kind"] == "mission" for e in recent)
    contracts_selected = sum(e["kind"] == "contract_selected" for e in recent)
    contracts_completed = sum(e["kind"] == "contract_completed" for e in recent)
    actions = sum(
        e["kind"] in ("case", "wheel", "conversion", "code", "contract_selected", "contract_completed") for e in recent
    )
    days = {e["at"].date() for e in past}
    streak = 0
    day = now.date() if now.date() in days else now.date() - timedelta(days=1)
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    last = max((e["at"] for e in past), default=None)
    age = (now.date() - last.date()).days if last else 99999
    parts = {
        "telegram": 20 if telegram_connected else 0,
        "missions": (0, 10, 18, 25)[min(missions, 3)],
        "mechanics": 0 if actions == 0 else 8 if actions <= 2 else 14 if actions <= 4 else 20,
        "streak": 0 if streak == 0 else 5 if streak == 1 else 10 if streak == 2 else 15 if streak <= 4 else 20,
        "recency": 15 if age <= 7 else 10 if age <= 14 else 5 if age <= 30 else 0,
    }
    score = sum(parts.values()) if telegram_connected is not None else None
    return {
        "score": score,
        "level": None if score is None else "HIGH" if score >= 70 else "MEDIUM" if score >= 35 else "LOW",
        "telegram_connected": telegram_connected,
        "missions_completed_30d": missions,
        "contracts_selected_30d": contracts_selected,
        "contracts_completed_30d": contracts_completed,
        "cb_actions_30d": actions,
        "current_streak": streak,
        "last_cb_activity_at": last,
        "components": parts,
    }


def audience(row, config=None):
    cfg = config or GUEST_PULSE_CONFIG
    s, h, v, e = row["lifecycle_status"], row["health"]["score"], row["value"]["score"], row["engagement"]["score"]
    if s in ("NEW", "ACTIVATING"):
        return "new"
    if s == "CHURNED":
        return "churned"
    if v is not None and v >= cfg["high_value_min"] and h is not None and h < cfg["stable_min"]:
        return "valuable_risk"
    if h is not None and h >= cfg["stable_min"] and e is not None and e < 35:
        return "low_engagement"
    if (
        h is not None
        and h >= cfg["stable_min"]
        and v is not None
        and v >= cfg["high_value_min"]
        and e is not None
        and e >= 35
    ):
        return "loyal"
    if h is not None and h < cfg["stable_min"]:
        return "risk"
    return "other"


def add_history(row, history, today):
    history = [x for x in history if today - timedelta(days=30) <= x["snapshot_date"] < today]
    by_date = {x["snapshot_date"]: x for x in history}
    for key in ("health", "value", "engagement"):
        values = [x[f"{key}_score"] for x in history if x[f"{key}_score"] is not None]
        base = median(values) if len(values) >= 7 else None
        current = row[key]["score"]
        row[key]["baseline_estimated"] = key == "engagement" and any(x.get("reconstructed") for x in history)
        row[key]["baseline_30d"] = base
        row[key]["baseline_days"] = len(values)
        row[key]["deviation_ratio"] = (
            abs(current - base) / max(base, 1) if current is not None and base is not None else None
        )
        row[key]["deviation_points"] = (
            round(current - base, 2) if current is not None and base is not None else None
        )
        row[key]["deviation_percent"] = (
            round((current - base) / max(base, 1) * 100, 2)
            if current is not None and base is not None
            else None
        )
        row[key]["deviation_direction"] = (
            None if current is None or base is None or current == base else "UP" if current > base else "DOWN"
        )
    for d in (7, 14, 30):
        old = by_date.get(today - timedelta(days=d), {}).get("health_score")
        row["health"][f"score_{d}d_ago"] = old
        row["health"][f"delta_{d}d"] = (
            round(row["health"]["score"] - old, 2) if row["health"]["score"] is not None and old is not None else None
        )
    delta = row["health"]["delta_14d"]
    row["health"]["trend_label"] = (
        None
        if delta is None
        else (
            "STRONG_GROWTH"
            if delta >= 15
            else "GROWTH" if delta >= 5 else "STABLE" if delta > -5 else "DECLINE" if delta > -15 else "STRONG_DECLINE"
        )
    )
    return row
