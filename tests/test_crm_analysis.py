from app.services.crm_analysis import _build_funnel_period_filter, get_crm_cohort_analysis


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


class _Cursor:
    def __init__(self):
        self.queries = []
        self.params = []
        self.fetchone_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append(query)
        self.params.append(params)

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return {
                "total_guests": 2,
                "telegram_guests": 1,
                "avg_session_minutes": 120,
                "avg_visits_per_month": 3.5,
                "night_share": 0.25,
                "weekend_share": 0.5,
                "avg_topup": 400,
            }
        return {
            "step_1": 2,
            "step_2": 1,
            "step_3": 0,
            "step_4": 0,
            "step_5": 0,
            "step_6": 0,
            "step_7": 0,
            "gap_1_2": 3,
        }


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()

    def cursor(self):
        return self.cursor_obj


def test_crm_analysis_funnel_uses_collapsed_visits_and_labels_visits():
    conn = _Connection()

    analysis = get_crm_cohort_analysis(conn, 1, [], funnel_period="30")

    funnel_query = conn.cursor_obj.queries[1]
    assert "DATE_ADD(previous_stop, INTERVAL 2 HOUR)" in funnel_query
    assert "visit_number" in funnel_query
    assert analysis["metrics"][2]["label"] == "Визитов в месяц"
    assert analysis["metrics"][2]["hint"] == "Среднее число склеенных визитов на гостя"
