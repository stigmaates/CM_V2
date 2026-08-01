from app.services.crm_analysis import _build_funnel_period_filter


def test_funnel_period_defaults_to_all_time():
    sql, params, label = _build_funnel_period_filter("all")

    assert sql == ""
    assert params == []
    assert label == "за всё время"


def test_funnel_period_can_use_preset_window():
    sql, params, label = _build_funnel_period_filter("7")

    assert "INTERVAL %s DAY" in sql
    assert params == [7]
    assert label == "за последние 7 дней"


def test_funnel_period_can_use_custom_dates():
    sql, params, label = _build_funnel_period_filter("custom", "2026-07-01", "2026-07-31")

    assert "gs.date_start >= %s" in sql
    assert "DATE_ADD(%s, INTERVAL 1 DAY)" in sql
    assert params == ["2026-07-01", "2026-07-31"]
    assert label == "с 2026-07-01 по 2026-07-31"
