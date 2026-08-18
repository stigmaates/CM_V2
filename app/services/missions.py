import json
import re
from datetime import datetime, timedelta

from app.core import get_db_connection

MISSION_METRICS = {
    "visits_count": {
        "name": "Прийти N раз",
        "description": "Считает количество визитов гостя за период.",
        "target_label": "N — сколько раз нужно прийти",
        "target_hint": "Например: 3 = гость должен прийти 3 раза за выбранный период.",
        "config_fields": [],
    },
    "visits_min_hours_count": {
        "name": "Прийти N раз на X часов",
        "description": "Считает визиты длительностью не меньше X часов.",
        "target_label": "N — сколько таких визитов нужно",
        "target_hint": "N = количество визитов. X настраивается отдельным полем ниже.",
        "min_hours_label": "X — минимум часов за каждый визит",
        "config_fields": ["min_hours"],
    },
    "sessions_started_in_time_range_count": {
        "name": "Начать N сессий в промежуток времени",
        "description": "Считает сессии, начатые в заданный интервал времени суток.",
        "target_label": "N — сколько сессий нужно начать",
        "target_hint": "Например: 4 = гость должен начать 4 сессии в выбранный временной интервал.",
        "time_start_label": "Начало интервала",
        "time_end_label": "Конец интервала",
        "config_fields": ["time_range"],
    },
    "night_hours_total": {
        "name": "Прийти на N часов ночью",
        "description": "Считает суммарное количество ночных игровых часов. Ночь: 22:00–08:00.",
        "target_label": "N — сколько ночных часов нужно отыграть",
        "target_hint": "Например: 10 = гость должен суммарно отыграть 10 часов ночью.",
        "config_fields": [],
    },
    "day_hours_total": {
        "name": "Прийти на N часов днём",
        "description": "Считает суммарное количество дневных игровых часов. День: 08:00–22:00.",
        "target_label": "N — сколько дневных часов нужно отыграть",
        "target_hint": "Например: 10 = гость должен суммарно отыграть 10 часов днём.",
        "config_fields": [],
    },
    "weekday_visits_min_hours_count": {
        "name": "Прийти N раз на X часов в будние",
        "description": "Считает будние визиты длительностью не меньше X часов.",
        "target_label": "N — сколько будних визитов нужно",
        "target_hint": "N = количество будних визитов. X настраивается отдельным полем ниже.",
        "min_hours_label": "X — минимум часов за каждый будний визит",
        "config_fields": ["min_hours"],
    },
    "weekend_visits_min_hours_count": {
        "name": "Прийти N раз на X часов в выходные",
        "description": "Считает визиты в субботу/воскресенье длительностью не меньше X часов.",
        "target_label": "N — сколько выходных визитов нужно",
        "target_hint": "N = количество визитов в выходные. X настраивается отдельным полем ниже.",
        "min_hours_label": "X — минимум часов за каждый визит в выходные",
        "config_fields": ["min_hours"],
    },
    "wheel_spins_count": {
        "name": "Провернуть колесо N раз",
        "description": "Считает количество прокрутов колеса фортуны.",
        "target_label": "N — сколько прокрутов нужно сделать",
        "target_hint": "Например: 5 = гость должен прокрутить колесо 5 раз.",
        "config_fields": [],
    },
    "case_openings_count": {
        "name": "Открыть кейсы N раз",
        "description": "Считает количество открытий любых кейсов.",
        "target_label": "N — сколько открытий кейсов нужно сделать",
        "target_hint": "Например: 3 = гость должен открыть любые кейсы 3 раза.",
        "config_fields": [],
    },
    "specific_case_openings_count": {
        "name": "Открыть выбранный кейс N раз",
        "description": "Считает количество открытий выбранного активного кейса.",
        "target_label": "N — сколько раз нужно открыть выбранный кейс",
        "target_hint": "Например: 2 = открыть выбранный кейс 2 раза.",
        "config_fields": ["case_id"],
    },
    "completed_missions_count": {
        "name": "Выполнить N заданий",
        "description": "Считает количество других выполненных заданий клуба.",
        "target_label": "N — сколько других заданий нужно выполнить",
        "target_hint": "Текущее задание не считается, чтобы не было рекурсии.",
        "config_fields": [],
    },
    "consecutive_days_count": {
        "name": "Посетить клуб N дней подряд",
        "description": "Считает максимальную серию дней подряд с визитами.",
        "target_label": "N — сколько дней подряд нужно прийти",
        "target_hint": "Например: 3 = визит в клуб 3 календарных дня подряд.",
        "config_fields": [],
    },
    "total_hours": {
        "name": "Отыграть суммарно N часов",
        "description": "Считает суммарное количество игровых часов за период.",
        "target_label": "N — сколько часов нужно отыграть суммарно",
        "target_hint": "Например: 20 = гость должен суммарно отыграть 20 часов.",
        "config_fields": [],
    },
    # Старые метрики оставлены для совместимости с уже созданными заданиями.
    "night_visits_count": {
        "name": "Ночные визиты",
        "description": "Считает визиты, начавшиеся ночью.",
        "target_label": "N — сколько ночных визитов нужно",
        "target_hint": "Старая механика: считает визиты, начавшиеся ночью.",
        "config_fields": [],
    },
    "weekend_visits_count": {
        "name": "Визиты в выходные",
        "description": "Считает визиты, начавшиеся в субботу или воскресенье.",
        "target_label": "N — сколько визитов в выходные нужно",
        "target_hint": "Старая механика: считает визиты, начавшиеся в выходной.",
        "config_fields": [],
    },
    "long_visits_count": {
        "name": "Длинные сессии",
        "description": "Считает визиты длительностью не меньше X часов.",
        "target_label": "N — сколько длинных визитов нужно",
        "target_hint": "N = количество визитов. X настраивается отдельным полем ниже.",
        "min_hours_label": "X — минимум часов за визит",
        "config_fields": ["min_hours"],
    },
}
DEFAULT_MISSION_TEMPLATES = [
    {
        "code": "visits_count",
        "name": "Прийти N раз",
        "short_description": "Посетить клуб нужное количество раз за период.",
        "target_metric": "visits_count",
    },
    {
        "code": "visits_min_hours_count",
        "name": "Прийти N раз на X часов",
        "short_description": "Посетить клуб N раз, каждый визит должен быть не короче X часов.",
        "target_metric": "visits_min_hours_count",
        "config_schema": {"min_hours": {"label": "Минимум часов за визит", "min": 1, "default": 3}},
    },
    {
        "code": "sessions_started_in_time_range_count",
        "name": "Начать N сессий в промежуток времени",
        "short_description": "Начать N сессий в заданный временной интервал.",
        "target_metric": "sessions_started_in_time_range_count",
        "config_schema": {
            "time_start": {"label": "Начало интервала", "default": "18:00"},
            "time_end": {"label": "Конец интервала", "default": "23:00"},
        },
    },
    {
        "code": "night_hours_total",
        "name": "Прийти на N часов ночью",
        "short_description": "Отыграть нужное количество часов в ночное время 22:00–08:00.",
        "target_metric": "night_hours_total",
    },
    {
        "code": "day_hours_total",
        "name": "Прийти на N часов днём",
        "short_description": "Отыграть нужное количество часов в дневное время 08:00–22:00.",
        "target_metric": "day_hours_total",
    },
    {
        "code": "weekday_visits_min_hours_count",
        "name": "Прийти N раз на X часов в будние",
        "short_description": "Сделать N будних визитов, каждый не короче X часов.",
        "target_metric": "weekday_visits_min_hours_count",
        "config_schema": {"min_hours": {"label": "Минимум часов за визит", "min": 1, "default": 3}},
    },
    {
        "code": "weekend_visits_min_hours_count",
        "name": "Прийти N раз на X часов в выходные",
        "short_description": "Сделать N визитов в выходные, каждый не короче X часов.",
        "target_metric": "weekend_visits_min_hours_count",
        "config_schema": {"min_hours": {"label": "Минимум часов за визит", "min": 1, "default": 3}},
    },
    {
        "code": "wheel_spins_count",
        "name": "Провернуть колесо N раз",
        "short_description": "Сделать нужное количество прокрутов колеса фортуны.",
        "target_metric": "wheel_spins_count",
    },
    {
        "code": "case_openings_count",
        "name": "Открыть кейсы N раз",
        "short_description": "Открыть любые кейсы нужное количество раз.",
        "target_metric": "case_openings_count",
    },
    {
        "code": "specific_case_openings_count",
        "name": "Открыть выбранный кейс N раз",
        "short_description": "Открыть выбранный активный кейс нужное количество раз.",
        "target_metric": "specific_case_openings_count",
        "config_schema": {"case_id": {"label": "Кейс", "source": "active_cases"}},
    },
    {
        "code": "completed_missions_count",
        "name": "Выполнить N заданий",
        "short_description": "Выполнить нужное количество других активных заданий клуба.",
        "target_metric": "completed_missions_count",
    },
    {
        "code": "consecutive_days_count",
        "name": "Посетить клуб N дней подряд",
        "short_description": "Собрать серию из N дней подряд с визитами в клуб.",
        "target_metric": "consecutive_days_count",
    },
    {
        "code": "total_hours",
        "name": "Отыграть суммарно N часов",
        "short_description": "Отыграть суммарно нужное количество часов за период.",
        "target_metric": "total_hours",
    },
]


def build_guest_mission_reward_display(reward_text, token_reward: int, cm_bonus_reward: int = 0) -> str:
    """Одна строка награды для гостя: текстовый приз + жетоны + КБ без дублей."""
    rt = (reward_text or "").strip()
    tr = max(int(token_reward or 0), 0)
    br = max(int(cm_bonus_reward or 0), 0)

    parts = []
    if rt:
        parts.append(rt)

    lowered = rt.lower()
    if tr > 0:
        token_line = f"🪙 +{tr} жет."
        if not ("жет" in lowered and re.search(rf"(?:^|\D){tr}(?!\d)", rt)):
            parts.append(token_line)

    if br > 0:
        bonus_line = f"🎁 +{br} КБ"
        if not (("cm" in lowered or "см" in lowered or "бонус" in lowered) and re.search(rf"(?:^|\D){br}(?!\d)", rt)):
            parts.append(bonus_line)

    return " · ".join(parts)


_BONUS_QUANTITY_IN_REWARD_TEXT = re.compile(
    r"(?i)\d[\d\s.,]*\s*(бонус(?:ов|а|ы)?|bonus(?:es)?)\b" r"|\b(бонус(?:ов|а|ы)?|bonus(?:es)?)\s*[:\-–+]?\s*\d"
)


def reward_text_contains_bonus_quantity(reward_text: str | None) -> bool:
    """True, если в поле «Приз» указано количество бонусов — это дублирует КБ."""
    if not reward_text or not str(reward_text).strip():
        return False
    t = str(reward_text).lower().replace("ё", "е")
    return bool(_BONUS_QUANTITY_IN_REWARD_TEXT.search(t))


_mission_reward_columns_ready = False
_mission_templates_seeded = False


def ensure_mission_reward_columns(cursor):
    """Make older databases compatible with mission rewards."""
    global _mission_reward_columns_ready
    if _mission_reward_columns_ready:
        return

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'reward_text'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE club_missions " "ADD COLUMN reward_text VARCHAR(255) NULL AFTER target_amount")

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'token_reward'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE club_missions " "ADD COLUMN token_reward INT NOT NULL DEFAULT 0 AFTER reward_text")

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'cm_bonus_reward'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE club_missions " "ADD COLUMN cm_bonus_reward INT NOT NULL DEFAULT 0 AFTER token_reward"
        )

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'custom_name'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE club_missions " "ADD COLUMN custom_name VARCHAR(255) NULL AFTER mission_template_id"
        )

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'custom_description'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE club_missions " "ADD COLUMN custom_description TEXT NULL AFTER custom_name")

    _mission_reward_columns_ready = True


def ensure_mission_reward_text_column(cursor):
    ensure_mission_reward_columns(cursor)


def _config_schema_for_metric(metric: str, explicit_schema=None):
    if explicit_schema:
        return explicit_schema
    metric_info = MISSION_METRICS.get(metric) or {}
    if "min_hours" in metric_info.get("config_fields", []):
        return {
            "min_hours": {
                "label": metric_info.get("min_hours_label") or "X — минимум часов за визит",
                "min": 1,
                "default": 3,
            }
        }
    if "case_id" in metric_info.get("config_fields", []):
        return {"case_id": {"label": "Кейс", "source": "active_cases"}}
    if "time_range" in metric_info.get("config_fields", []):
        return {
            "time_start": {"label": metric_info.get("time_start_label") or "Начало интервала", "default": "18:00"},
            "time_end": {"label": metric_info.get("time_end_label") or "Конец интервала", "default": "23:00"},
        }
    return None


def _decode_json(value):
    if value and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def _enrich_mission_row(row):
    row["config"] = _decode_json(row.get("config"))
    row["config_schema"] = _decode_json(row.get("config_schema"))
    row["display_name"] = (row.get("custom_name") or row.get("name") or "").strip()
    metric = row.get("target_metric")
    row["metric_info"] = MISSION_METRICS.get(metric, {})
    row["requires_min_hours"] = "min_hours" in (row["metric_info"].get("config_fields") or [])
    row["requires_case_select"] = "case_id" in (row["metric_info"].get("config_fields") or [])
    row["requires_time_range"] = "time_range" in (row["metric_info"].get("config_fields") or [])
    row["target_label"] = row["metric_info"].get("target_label") or "Цель"
    row["target_hint"] = row["metric_info"].get("target_hint") or ""
    row["min_hours_label"] = row["metric_info"].get("min_hours_label") or "X — минимум часов за визит"
    row["time_start_label"] = row["metric_info"].get("time_start_label") or "Начало интервала"
    row["time_end_label"] = row["metric_info"].get("time_end_label") or "Конец интервала"
    if row.get("config") is None:
        row["config"] = {}
    return row


def _enrich_template_row(row):
    row["config_schema"] = _decode_json(row.get("config_schema"))
    metric = row.get("target_metric")
    row["metric_info"] = MISSION_METRICS.get(metric, {})
    row["requires_min_hours"] = "min_hours" in (row["metric_info"].get("config_fields") or [])
    row["requires_case_select"] = "case_id" in (row["metric_info"].get("config_fields") or [])
    row["requires_time_range"] = "time_range" in (row["metric_info"].get("config_fields") or [])
    row["target_label"] = row["metric_info"].get("target_label") or "Цель"
    row["target_hint"] = row["metric_info"].get("target_hint") or ""
    row["min_hours_label"] = row["metric_info"].get("min_hours_label") or "X — минимум часов за визит"
    row["time_start_label"] = row["metric_info"].get("time_start_label") or "Начало интервала"
    row["time_end_label"] = row["metric_info"].get("time_end_label") or "Конец интервала"
    if not row.get("config_schema"):
        row["config_schema"] = _config_schema_for_metric(metric)
    return row


def ensure_default_mission_templates(cursor):
    """Seed/update default templates. New mechanics become available without manual SQL."""
    global _mission_templates_seeded
    if _mission_templates_seeded:
        return

    for item in DEFAULT_MISSION_TEMPLATES:
        schema = _config_schema_for_metric(item["target_metric"], item.get("config_schema"))
        schema_json = json.dumps(schema, ensure_ascii=False) if schema else None
        cursor.execute("SELECT id FROM mission_templates WHERE code = %s LIMIT 1", (item["code"],))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE mission_templates
                SET name = %s,
                    short_description = %s,
                    target_metric = %s,
                    config_schema = %s,
                    is_active = 1
                WHERE code = %s
                """,
                (item["name"], item["short_description"], item["target_metric"], schema_json, item["code"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO mission_templates
                    (code, name, short_description, target_metric, config_schema, is_active)
                VALUES (%s, %s, %s, %s, %s, 1)
                """,
                (item["code"], item["name"], item["short_description"], item["target_metric"], schema_json),
            )

    cursor.execute("""
        UPDATE mission_templates
        SET is_active = 0
        WHERE code = 'visits_in_period_count'
        """)

    _mission_templates_seeded = True


def get_mission_templates():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_default_mission_templates(cursor)
            conn.commit()
            cursor.execute("""
                SELECT id, code, name, short_description, target_metric, config_schema
                FROM mission_templates
                WHERE is_active = 1
                ORDER BY id
                """)
            return [_enrich_template_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_mission_template_by_id(template_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_default_mission_templates(cursor)
            conn.commit()
            cursor.execute(
                """
                SELECT id, code, name, short_description, target_metric, config_schema
                FROM mission_templates
                WHERE id = %s
                LIMIT 1
                """,
                (template_id,),
            )
            row = cursor.fetchone()
            return _enrich_template_row(row) if row else None
    finally:
        conn.close()


def _decode_mission_rows(rows):
    return [_enrich_mission_row(row) for row in rows]


def get_club_missions(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            ensure_default_mission_templates(cursor)
            conn.commit()
            cursor.execute(
                """
                SELECT cm.id,
                       cm.club_id,
                       cm.mission_template_id,
                       cm.custom_name,
                       cm.custom_description,
                       cm.target_amount,
                       cm.reward_text,
                       cm.token_reward,
                       cm.cm_bonus_reward,
                       cm.start_at,
                       cm.end_at,
                       cm.config,
                       cm.is_enabled,
                       cm.sort_order,
                       mt.code,
                       mt.name,
                       mt.short_description,
                       mt.target_metric,
                       mt.config_schema
                FROM club_missions cm
                JOIN mission_templates mt ON mt.id = cm.mission_template_id
                WHERE cm.club_id = %s
                  AND cm.is_enabled = 1
                  AND (cm.start_at IS NULL OR cm.start_at <= NOW())
                  AND (cm.end_at IS NULL OR cm.end_at >= NOW())
                ORDER BY cm.sort_order, cm.id
                """,
                (club_id,),
            )
            return _decode_mission_rows(cursor.fetchall())
    finally:
        conn.close()


def get_club_missions_all(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            ensure_default_mission_templates(cursor)
            conn.commit()
            cursor.execute(
                """
                SELECT cm.id,
                       cm.club_id,
                       cm.mission_template_id,
                       cm.custom_name,
                       cm.custom_description,
                       cm.target_amount,
                       cm.reward_text,
                       cm.token_reward,
                       cm.cm_bonus_reward,
                       cm.start_at,
                       cm.end_at,
                       cm.config,
                       cm.is_enabled,
                       cm.sort_order,
                       mt.code,
                       mt.name,
                       mt.short_description,
                       mt.target_metric,
                       mt.config_schema
                FROM club_missions cm
                JOIN mission_templates mt ON mt.id = cm.mission_template_id
                WHERE cm.club_id = %s
                ORDER BY cm.sort_order, cm.id
                """,
                (club_id,),
            )
            return _decode_mission_rows(cursor.fetchall())
    finally:
        conn.close()


def _next_club_mission_id(cursor) -> int:
    cursor.execute("""
        SELECT COALESCE(MAX(id), 0) + 1 AS next_id
        FROM club_missions
        """)
    row = cursor.fetchone() or {}
    return int(row.get("next_id") or 1)


def build_period_filter(mission, date_field="date_start"):
    start_at = mission.get("start_at")
    end_at = mission.get("end_at")
    conditions = []
    params = []

    if start_at:
        conditions.append(f"{date_field} >= %s")
        params.append(start_at)
    if end_at:
        conditions.append(f"{date_field} <= %s")
        params.append(end_at)

    return conditions, params


def _mission_requires_min_hours(template_or_mission) -> bool:
    metric = template_or_mission.get("target_metric")
    schema = template_or_mission.get("config_schema")
    if isinstance(schema, str):
        schema = _decode_json(schema)
    if isinstance(schema, dict) and "min_hours" in schema:
        return True
    return "min_hours" in (MISSION_METRICS.get(metric, {}).get("config_fields") or [])


def _mission_requires_case_select(template_or_mission) -> bool:
    metric = template_or_mission.get("target_metric")
    schema = template_or_mission.get("config_schema")
    if isinstance(schema, str):
        schema = _decode_json(schema)
    if isinstance(schema, dict) and "case_id" in schema:
        return True
    return "case_id" in (MISSION_METRICS.get(metric, {}).get("config_fields") or [])


def _mission_requires_time_range(template_or_mission) -> bool:
    metric = template_or_mission.get("target_metric")
    schema = template_or_mission.get("config_schema")
    if isinstance(schema, str):
        schema = _decode_json(schema)
    if isinstance(schema, dict) and ("time_start" in schema or "time_end" in schema):
        return True
    return "time_range" in (MISSION_METRICS.get(metric, {}).get("config_fields") or [])


def _validate_time_of_day(value: str, field_name: str) -> str:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        raise ValueError(f"{field_name} должен быть в формате ЧЧ:ММ")
    return value


def build_mission_config_from_form(template, form):
    config = {}

    if _mission_requires_min_hours(template):
        min_hours = form.get("min_hours", "").strip()
        if not min_hours:
            raise ValueError("Укажи минимальное количество часов")
        try:
            min_hours = int(min_hours)
        except ValueError:
            raise ValueError("Минимум часов должен быть числом")
        if min_hours <= 0:
            raise ValueError("Минимум часов должен быть больше 0")
        config["min_hours"] = min_hours

    if _mission_requires_case_select(template):
        case_id = form.get("case_id", "").strip()
        if not case_id:
            raise ValueError("Выбери кейс для задания")
        try:
            case_id = int(case_id)
        except ValueError:
            raise ValueError("Кейс должен быть выбран из списка")
        if case_id <= 0:
            raise ValueError("Выбери кейс для задания")
        config["case_id"] = case_id

    if _mission_requires_time_range(template):
        time_start = form.get("time_start", "").strip()
        time_end = form.get("time_end", "").strip()
        if not time_start or not time_end:
            raise ValueError("Укажи начало и конец временного интервала")
        config["time_start"] = _validate_time_of_day(time_start, "Начало интервала")
        config["time_end"] = _validate_time_of_day(time_end, "Конец интервала")

    return config or None


def create_club_mission(
    club_id: int,
    mission_template_id: int,
    target_amount: int,
    start_at=None,
    end_at=None,
    config=None,
    reward_text=None,
    token_reward: int = 0,
    cm_bonus_reward: int = 0,
    custom_name=None,
    custom_description=None,
):
    if start_at and end_at and end_at < start_at:
        raise ValueError("Дата окончания не может быть раньше даты начала")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            mission_id = _next_club_mission_id(cursor)
            cursor.execute(
                """
                INSERT INTO club_missions (
                    id,
                    club_id,
                    mission_template_id,
                    custom_name,
                    custom_description,
                    is_enabled,
                    target_amount,
                    reward_text,
                    token_reward,
                    cm_bonus_reward,
                    start_at,
                    end_at,
                    config,
                    sort_order
                )
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, 0)
                """,
                (
                    mission_id,
                    club_id,
                    mission_template_id,
                    custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None,
                    (
                        custom_description.strip()
                        if isinstance(custom_description, str) and custom_description.strip()
                        else None
                    ),
                    target_amount,
                    reward_text.strip() if isinstance(reward_text, str) and reward_text.strip() else None,
                    max(int(token_reward or 0), 0),
                    max(int(cm_bonus_reward or 0), 0),
                    start_at,
                    end_at,
                    json.dumps(config, ensure_ascii=False) if config else None,
                ),
            )
        conn.commit()
        return mission_id
    finally:
        conn.close()


def update_club_mission(
    mission_id: int,
    club_id: int,
    target_amount: int,
    start_at=None,
    end_at=None,
    config=None,
    is_enabled=1,
    reward_text=None,
    token_reward: int = 0,
    cm_bonus_reward: int = 0,
    custom_name=None,
    custom_description=None,
):
    if start_at and end_at and end_at < start_at:
        raise ValueError("Дата окончания не может быть раньше даты начала")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            cursor.execute(
                """
                UPDATE club_missions
                SET custom_name = %s,
                    custom_description = %s,
                    target_amount = %s,
                    reward_text = %s,
                    token_reward = %s,
                    cm_bonus_reward = %s,
                    start_at = %s,
                    end_at = %s,
                    config = %s,
                    is_enabled = %s
                WHERE id = %s
                  AND club_id = %s
                """,
                (
                    custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None,
                    (
                        custom_description.strip()
                        if isinstance(custom_description, str) and custom_description.strip()
                        else None
                    ),
                    target_amount,
                    reward_text.strip() if isinstance(reward_text, str) and reward_text.strip() else None,
                    max(int(token_reward or 0), 0),
                    max(int(cm_bonus_reward or 0), 0),
                    start_at,
                    end_at,
                    json.dumps(config, ensure_ascii=False) if config else None,
                    is_enabled,
                    mission_id,
                    club_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def disable_club_mission(mission_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE club_missions
                SET is_enabled = 0
                WHERE id = %s
                  AND club_id = %s
                """,
                (mission_id, club_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_club_mission(mission_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM club_missions
                WHERE id = %s
                  AND club_id = %s
                """,
                (mission_id, club_id),
            )
        conn.commit()
    finally:
        conn.close()


def _session_duration_hours(row) -> float:
    start = row.get("date_start")
    stop = row.get("date_stop")
    if not start or not stop or stop <= start:
        return 0.0
    return (stop - start).total_seconds() / 3600


def _collapse_sessions_to_visits(rows, gap_hours: int = 2):
    visits = []
    max_gap = timedelta(hours=gap_hours)

    for row in sorted(rows or [], key=lambda item: item.get("date_start") or datetime.min):
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


def _fetch_sessions(cursor, guest_id: int, club_id: int, mission):
    period_conditions, period_params = build_period_filter(mission)
    where_parts = [
        "guest_id = %s",
        "club_id = %s",
        "date_start IS NOT NULL",
        "date_stop IS NOT NULL",
    ] + period_conditions
    params = [guest_id, club_id] + period_params
    sql = f"""
        SELECT date_start, date_stop
        FROM guest_sessions
        WHERE {' AND '.join(where_parts)}
        ORDER BY date_start
    """
    cursor.execute(sql, params)
    return cursor.fetchall()


def _fetch_visits(cursor, guest_id: int, club_id: int, mission):
    return _collapse_sessions_to_visits(_fetch_sessions(cursor, guest_id, club_id, mission))


def _overlap_seconds(start, stop, window_start, window_end) -> float:
    latest_start = max(start, window_start)
    earliest_end = min(stop, window_end)
    delta = (earliest_end - latest_start).total_seconds()
    return max(delta, 0)


def _night_overlap_hours(start, stop) -> float:
    if not start or not stop or stop <= start:
        return 0.0
    total = 0.0
    day = start.date() - timedelta(days=1)
    end_day = stop.date()
    while day <= end_day:
        night_start = datetime.combine(day, datetime.min.time()).replace(hour=22)
        night_end = night_start + timedelta(hours=10)
        total += _overlap_seconds(start, stop, night_start, night_end)
        day += timedelta(days=1)
    return total / 3600


def _day_overlap_hours(start, stop) -> float:
    if not start or not stop or stop <= start:
        return 0.0
    total = 0.0
    day = start.date()
    end_day = stop.date()
    while day <= end_day:
        day_start = datetime.combine(day, datetime.min.time()).replace(hour=8)
        day_end = datetime.combine(day, datetime.min.time()).replace(hour=22)
        total += _overlap_seconds(start, stop, day_start, day_end)
        day += timedelta(days=1)
    return total / 3600


def _max_consecutive_day_streak(dates) -> int:
    if not dates:
        return 0
    days = sorted(set(dates))
    best = 1
    current = 1
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days == 1:
            current += 1
        else:
            best = max(best, current)
            current = 1
    return max(best, current)


def _get_min_hours(mission) -> int:
    config = mission.get("config") or {}
    if isinstance(config, str):
        config = _decode_json(config) or {}
    if isinstance(config, dict):
        return int(config.get("min_hours", 0) or 0)
    return 0


def _get_time_range(mission):
    config = mission.get("config") or {}
    if isinstance(config, str):
        config = _decode_json(config) or {}
    if isinstance(config, dict):
        try:
            time_start = datetime.strptime(str(config.get("time_start") or ""), "%H:%M").time()
            time_end = datetime.strptime(str(config.get("time_end") or ""), "%H:%M").time()
        except ValueError:
            return None
        return time_start, time_end
    return None


def _time_in_range(value, time_start, time_end) -> bool:
    if time_start <= time_end:
        return time_start <= value < time_end
    return value >= time_start or value < time_end


def _count_visits(cursor, guest_id: int, club_id: int, mission, predicate=None) -> int:
    visits = _fetch_visits(cursor, guest_id, club_id, mission)
    if predicate is None:
        return len(visits)
    return sum(1 for visit in visits if predicate(visit))


def _count_sessions_started_in_time_range(cursor, guest_id: int, club_id: int, mission) -> int:
    time_range = _get_time_range(mission)
    if not time_range:
        return 0

    time_start, time_end = time_range
    sessions = _fetch_sessions(cursor, guest_id, club_id, mission)
    return sum(
        1
        for session in sessions
        if session.get("date_start") and _time_in_range(session["date_start"].time(), time_start, time_end)
    )


def _count_case_openings(cursor, guest_id: int, club_id: int, mission, case_id: int | None = None) -> int:
    period_conditions, period_params = build_period_filter(mission, date_field="created_at")
    where_parts = ["guest_id = %s", "club_id = %s"] + period_conditions
    params = [guest_id, club_id] + period_params
    if case_id:
        where_parts.append("case_id = %s")
        params.append(case_id)
    sql = f"SELECT COUNT(*) AS cnt FROM guest_case_openings WHERE {' AND '.join(where_parts)}"
    cursor.execute(sql, params)
    return cursor.fetchone()["cnt"] or 0


def _calculate_completed_missions_progress(cursor, guest_id: int, club_id: int, current_mission):
    # Считаем только другие задания, чтобы не получить рекурсию «выполни N заданий» внутри самого себя.
    completed = 0
    for mission in get_club_missions(club_id):
        if mission.get("id") == current_mission.get("id"):
            continue
        if mission.get("target_metric") == "completed_missions_count":
            continue
        target = int(mission.get("target_amount") or 0)
        if target <= 0:
            continue
        progress = calculate_mission_progress(guest_id, club_id, mission)
        if progress >= target:
            completed += 1
    return completed


def calculate_mission_progress(guest_id: int, club_id: int, mission):
    metric = mission["target_metric"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if metric == "visits_count":
                return _count_visits(cursor, guest_id, club_id, mission)

            if metric == "sessions_started_in_time_range_count":
                return _count_sessions_started_in_time_range(cursor, guest_id, club_id, mission)

            if metric == "night_visits_count":
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: visit["date_start"].hour >= 22 or visit["date_start"].hour < 8,
                )

            if metric == "weekend_visits_count":
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: visit["date_start"].isoweekday() in (6, 7),
                )

            if metric == "long_visits_count":
                min_hours = _get_min_hours(mission)
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: _session_duration_hours(visit) >= min_hours,
                )

            if metric == "visits_min_hours_count":
                min_hours = _get_min_hours(mission)
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: _session_duration_hours(visit) >= min_hours,
                )

            if metric == "weekday_visits_min_hours_count":
                min_hours = _get_min_hours(mission)
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: visit["date_start"].weekday() <= 4
                    and _session_duration_hours(visit) >= min_hours,
                )

            if metric == "weekend_visits_min_hours_count":
                min_hours = _get_min_hours(mission)
                return _count_visits(
                    cursor,
                    guest_id,
                    club_id,
                    mission,
                    predicate=lambda visit: visit["date_start"].weekday() in (5, 6)
                    and _session_duration_hours(visit) >= min_hours,
                )

            if metric == "total_hours":
                visits = _fetch_visits(cursor, guest_id, club_id, mission)
                return int(sum(_session_duration_hours(visit) for visit in visits))

            if metric == "night_hours_total":
                visits = _fetch_visits(cursor, guest_id, club_id, mission)
                return int(sum(_night_overlap_hours(v["date_start"], v["date_stop"]) for v in visits))

            if metric == "day_hours_total":
                visits = _fetch_visits(cursor, guest_id, club_id, mission)
                return int(sum(_day_overlap_hours(v["date_start"], v["date_stop"]) for v in visits))

            if metric == "consecutive_days_count":
                visits = _fetch_visits(cursor, guest_id, club_id, mission)
                return _max_consecutive_day_streak([v["date_start"].date() for v in visits if v.get("date_start")])

            if metric == "wheel_spins_count":
                period_conditions, period_params = build_period_filter(mission, date_field="created_at")
                where_parts = ["guest_id = %s", "club_id = %s"] + period_conditions
                params = [guest_id, club_id] + period_params
                sql = f"SELECT COUNT(*) AS cnt FROM guest_wheel_spins WHERE {' AND '.join(where_parts)}"
                cursor.execute(sql, params)
                return cursor.fetchone()["cnt"] or 0

            if metric == "case_openings_count":
                return _count_case_openings(cursor, guest_id, club_id, mission)

            if metric == "specific_case_openings_count":
                config = mission.get("config") or {}
                if isinstance(config, str):
                    config = _decode_json(config) or {}
                case_id = int((config or {}).get("case_id") or 0)
                if case_id <= 0:
                    return 0
                return _count_case_openings(cursor, guest_id, club_id, mission, case_id=case_id)

            if metric == "completed_missions_count":
                return _calculate_completed_missions_progress(cursor, guest_id, club_id, mission)

            return 0
    finally:
        conn.close()


def get_guest_missions_with_progress(guest_id: int, club_id: int):
    missions = get_club_missions(club_id)
    result = []

    for mission in missions:
        progress = calculate_mission_progress(guest_id, club_id, mission)
        target = mission["target_amount"] or 0
        progress_percent = round(min(progress / target, 1) * 100) if target > 0 else 0

        reward_text = mission.get("reward_text")
        token_reward = int(mission.get("token_reward") or 0)
        cm_bonus_reward = int(mission.get("cm_bonus_reward") or 0)
        result.append(
            {
                "id": mission["id"],
                "name": mission.get("display_name") or mission["name"],
                "template_name": mission["name"],
                "description": (mission.get("custom_description") or "").strip(),
                "target": target,
                "reward_text": reward_text,
                "token_reward": token_reward,
                "cm_bonus_reward": cm_bonus_reward,
                "reward_display": build_guest_mission_reward_display(reward_text, token_reward, cm_bonus_reward),
                "progress": progress,
                "progress_percent": progress_percent,
                "is_completed": progress >= target if target > 0 else False,
                "start_at": mission.get("start_at"),
                "end_at": mission.get("end_at"),
            }
        )

    return result
