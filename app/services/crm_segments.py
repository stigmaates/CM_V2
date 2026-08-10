from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CRM_STATUS_META = {
    "top": {"label": "Лучшие", "score": 6},
    "base": {"label": "База", "score": 5},
    "rare": {"label": "Редкие", "score": 4},
    "risk": {"label": "Риск", "score": 3},
    "lost": {"label": "Потерянные", "score": 2},
    "dead": {"label": "Давно без визита", "score": 1},
    "no_visits": {"label": "Без визитов", "score": 0},
}


@dataclass(frozen=True)
class CRMSegmentDecision:
    crm_type: str
    reason: str


def calculate_crm_segment(
    *,
    total_visits: int,
    visits_30d: int,
    visits_90d: int,
    days_since_last_visit: Optional[int],
) -> CRMSegmentDecision:
    if total_visits <= 0:
        return CRMSegmentDecision("no_visits", "нет визитов")

    if days_since_last_visit is not None:
        if days_since_last_visit >= 90:
            return CRMSegmentDecision("dead", f"не был {days_since_last_visit} дн.")
        if days_since_last_visit >= 30:
            return CRMSegmentDecision("lost", f"не был {days_since_last_visit} дн.")
        if days_since_last_visit >= 14:
            return CRMSegmentDecision("risk", f"не был {days_since_last_visit} дн.")

    if visits_30d >= 8:
        return CRMSegmentDecision("top", f"{visits_30d} визитов за 30 дней")

    if visits_90d >= 18 and visits_30d >= 4:
        return CRMSegmentDecision("top", f"{visits_30d} за 30 дн. и {visits_90d} за 90 дн.")

    if visits_30d >= 3:
        return CRMSegmentDecision("base", f"{visits_30d} визитов за 30 дней")

    if visits_90d >= 8 and visits_30d >= 2:
        return CRMSegmentDecision("base", f"{visits_30d} за 30 дн. и {visits_90d} за 90 дн.")

    return CRMSegmentDecision("rare", f"{visits_30d} визитов за 30 дней")
