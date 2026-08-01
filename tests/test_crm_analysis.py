from app.services.crm_analysis import _infer_funnel_period_days


def test_funnel_period_is_inferred_from_visit_filters():
    rules = [
        {"field": "crm_type", "op": "=", "value": "rare"},
        {"field": "visits_30d", "op": ">", "value": "2"},
    ]

    assert _infer_funnel_period_days(rules) == 30


def test_funnel_period_uses_most_specific_window_when_multiple_period_filters():
    rules = [
        {"field": "sessions_90d", "op": ">", "value": "4"},
        {"field": "visits_7d", "op": ">", "value": "1"},
    ]

    assert _infer_funnel_period_days(rules) == 7


def test_funnel_period_is_unbounded_without_period_filters():
    rules = [
        {"field": "crm_type", "op": "=", "value": "rare"},
        {"field": "age", "op": ">", "value": "20"},
    ]

    assert _infer_funnel_period_days(rules) is None
