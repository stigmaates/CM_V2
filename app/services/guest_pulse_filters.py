"""The same audience predicate is used by screen, drilldown and CRM handoff."""

import math

from app.config import GUEST_PULSE_CONFIG
from app.services.guest_pulse_scores import AUDIENCES, SEGMENTS


def parse_filters(args):
    if not hasattr(args, "get"):
        raise ValueError("Некорректные фильтры")
    result = {}
    for key, default, maximum in [
        ("health_min", 0, 100),
        ("health_max", 100, 100),
        ("value_min", 0, 100),
        ("value_max", 100, 100),
        ("engagement_min", 0, 100),
        ("engagement_max", 100, 100),
        ("deviation_min", 0.15, 100),
        ("deviation_max", 0.5, 100),
    ]:
        try:
            value = float(args.get(key, default))
        except (ValueError, TypeError):
            raise ValueError("Диапазоны должны содержать числа") from None
        if not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValueError("Значение диапазона вне допустимых границ")
        result[key] = value
    for key in ("health", "value", "engagement", "deviation"):
        if result[f"{key}_min"] > result[f"{key}_max"]:
            raise ValueError("Начало диапазона больше конца")
    result["audience_type"] = args.get("audience_type", "")
    result["metric"] = args.get("metric", "all")
    result["deviation_direction"] = args.get("deviation_direction", "all")
    result["segment"] = args.get("segment", "")
    if result["audience_type"] not in ("", *(x[0] for x in AUDIENCES)):
        raise ValueError("Неизвестный тип аудитории")
    if result["metric"] not in ("all", "health", "value", "engagement"):
        raise ValueError("Неизвестный показатель")
    if result["deviation_direction"] not in ("all", "up", "down"):
        raise ValueError("Неизвестное направление отклонения")
    if result["segment"] not in ("", *SEGMENTS):
        raise ValueError("Неизвестный сегмент")
    return result


def score_match(row, f):
    for key in ("health", "value", "engagement"):
        value = row[key]["score"]
        lo, hi = f[f"{key}_min"], f[f"{key}_max"]
        # Full range includes unscored newcomers; a restricted range does not.
        if value is None:
            if (lo, hi) != (0, 100):
                return False
        elif not lo <= value <= hi:
            return False
    return True


def segment_match(row, segment):
    h, v, e = (row[key]["score"] for key in ("health", "value", "engagement"))
    high = GUEST_PULSE_CONFIG["high_value_min"]
    stable = GUEST_PULSE_CONFIG["stable_min"]
    return {
        "": True,
        "high_value_at_risk": v is not None and v >= high and h is not None and h < stable,
        "strong_decline": row["health"].get("delta_14d") is not None
        and row["health"]["delta_14d"] <= GUEST_PULSE_CONFIG["health_drop_alert_14d"]
        and row["lifecycle_status"] != "CHURNED",
        "active_high_value": h is not None and h >= stable and v is not None and v >= high,
        "active_low_engagement": h is not None and h >= stable and e is not None and e < 35,
        "high_risk": row["lifecycle_status"] == "HIGH_RISK",
        "reactivated": row["lifecycle_status"] == "REACTIVATED",
        "new": row["lifecycle_status"] == "NEW",
        "activating": row["lifecycle_status"] == "ACTIVATING",
    }[segment]


def deviations(row, f):
    return [
        {"metric": key, **row[key]}
        for key in ("health", "value", "engagement")
        if f["metric"] in ("all", key)
        and row[key].get("deviation_ratio") is not None
        and f["deviation_min"] <= row[key]["deviation_ratio"] <= f["deviation_max"]
        and (
            f["deviation_direction"] == "all"
            or row[key].get("deviation_direction") == f["deviation_direction"].upper()
        )
    ]


def select(rows, f, mode="audience"):
    if mode == "deviations":
        return [{**r, "deviations": deviations(r, f)} for r in rows if deviations(r, f)]
    return [
        r
        for r in rows
        if score_match(r, f)
        and (not f["audience_type"] or r["audience_type"] == f["audience_type"])
        and segment_match(r, f["segment"])
    ]
