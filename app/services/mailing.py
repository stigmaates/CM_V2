import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from werkzeug.utils import secure_filename

from app.config import BALANCE_TOPUP_MAX_AMOUNT
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.wheel import _add_token_transaction, ensure_token_tables

CRM_SEGMENT_OPTIONS = [
    {
        "key": "top",
        "label": "Лучшие",
        "title": "Лучшие",
        "emoji": "👑",
        "description": "8+ визитов за 30 дней или 18+ за 90 дней при 4+ за 30 дней",
    },
    {
        "key": "base",
        "label": "База",
        "title": "База",
        "emoji": "👥",
        "description": "3–7 визитов за 30 дней или 8+ за 90 дней при 2+ за 30 дней",
    },
    {
        "key": "rare",
        "label": "Редкие",
        "title": "Редкие",
        "emoji": "✨",
        "description": "Были недавно, но не набрали активность для Базы",
    },
    {"key": "risk", "label": "Риск", "title": "Риск", "emoji": "⚠️", "description": "Не были 14–29 дней"},
    {
        "key": "dead",
        "label": "Давно без визита",
        "title": "Давно без визита",
        "emoji": "☠️",
        "description": "Не были 90+ дней",
    },
    {"key": "lost", "label": "Потерянные", "title": "Потерянные", "emoji": "💔", "description": "Не были 30–89 дней"},
    {
        "key": "no_visits",
        "label": "Без визитов",
        "title": "Без визитов",
        "emoji": "🆕",
        "description": "Есть в базе, без визитов",
    },
]

FILTER_FIELDS = {
    "phone": {"type": "phone_list", "column": "g.phone", "label": "Номер телефона"},
    "gender": {
        "type": "enum",
        "column": "up.gender",
        "label": "Пол",
        "options": [{"value": 1, "label": "Мужской"}, {"value": 2, "label": "Женский"}],
    },
    "age": {"type": "number", "column": "up.age", "label": "Возраст"},
    "registration_date": {"type": "date", "column": "up.registration_date", "label": "Дата регистрации"},
    "first_visit_date": {"type": "date", "column": "up.first_visit_date", "label": "Дата первого визита"},
    "last_visit_date": {"type": "date", "column": "up.last_visit_date", "label": "Дата последнего визита"},
    "visits_7d": {"type": "number", "column": "up.visits_7d", "label": "Визиты за 7 дней"},
    "visits_30d": {"type": "number", "column": "up.visits_30d", "label": "Визиты за 30 дней"},
    "visits_90d": {"type": "number", "column": "up.visits_90d", "label": "Визиты за 90 дней"},
    "sessions_7d": {
        "type": "number",
        "column": "(SELECT COUNT(*) FROM guest_sessions gs7 WHERE gs7.club_id = up.club_id AND gs7.guest_id = up.guest_id AND gs7.date_start >= DATE_SUB(NOW(), INTERVAL 7 DAY))",
        "label": "Сессии за 7 дней",
    },
    "sessions_30d": {
        "type": "number",
        "column": "(SELECT COUNT(*) FROM guest_sessions gs30 WHERE gs30.club_id = up.club_id AND gs30.guest_id = up.guest_id AND gs30.date_start >= DATE_SUB(NOW(), INTERVAL 30 DAY))",
        "label": "Сессии за 30 дней",
    },
    "sessions_90d": {
        "type": "number",
        "column": "(SELECT COUNT(*) FROM guest_sessions gs90 WHERE gs90.club_id = up.club_id AND gs90.guest_id = up.guest_id AND gs90.date_start >= DATE_SUB(NOW(), INTERVAL 90 DAY))",
        "label": "Сессии за 90 дней",
    },
    "total_visits": {"type": "number", "column": "up.total_visits", "label": "Всего визитов"},
    "avg_visits_per_month": {"type": "number", "column": "up.avg_visits_per_month", "label": "Среднее визитов в месяц"},
    "avg_session_minutes": {"type": "number", "column": "up.avg_session_minutes", "label": "Средняя длина визита"},
    "max_session_minutes": {"type": "number", "column": "up.max_session_minutes", "label": "Макс. длина сессии"},
    "total_hours_30d": {"type": "number", "column": "up.total_hours_30d", "label": "Часов за 30 дней"},
    "total_hours_all": {"type": "number", "column": "up.total_hours_all", "label": "Часов за всё время"},
    "days_since_last_visit": {
        "type": "number",
        "column": "up.days_since_last_visit",
        "label": "Дней с последнего визита",
    },
    "night_share": {"type": "number", "column": "up.night_share", "label": "Доля ночных визитов"},
    "weekend_share": {"type": "number", "column": "up.weekend_share", "label": "Доля визитов в выходные"},
    "favorite_period": {
        "type": "enum",
        "column": "up.favorite_period",
        "label": "Любимое время",
        "options": [
            {"value": "day", "label": "День"},
            {"value": "evening", "label": "Вечер"},
            {"value": "night", "label": "Ночь"},
        ],
    },
    "avg_check_all": {"type": "number", "column": "up.avg_check_all", "label": "Среднее пополнение за всё время"},
    "avg_check_30d": {"type": "number", "column": "up.avg_check_30d", "label": "Среднее пополнение за 30 дней"},
    "last_payment_date": {"type": "date", "column": "up.last_payment_date", "label": "Последнее пополнение"},
    "missions_completed_count": {
        "type": "number",
        "column": "up.missions_completed_count",
        "label": "Выполнено миссий",
    },
    "missions_in_progress_count": {
        "type": "number",
        "column": "up.missions_in_progress_count",
        "label": "Миссий в процессе",
    },
    "last_mission_activity_date": {
        "type": "date",
        "column": "up.last_mission_activity_date",
        "label": "Последняя активность по миссиям",
    },
    "spins_count": {"type": "number", "column": "up.spins_count", "label": "Количество прокрутов"},
    "last_spin_date": {"type": "date", "column": "up.last_spin_date", "label": "Последний прокрут"},
    "lifetime_days": {"type": "number", "column": "up.lifetime_days", "label": "Дней с первого визита"},
    "avg_days_between_visits": {
        "type": "number",
        "column": "up.avg_days_between_visits",
        "label": "Средний интервал между визитами",
    },
    "is_active_30d": {"type": "bool", "column": "up.is_active_30d", "label": "Активен за 30 дней"},
    "is_active_90d": {"type": "bool", "column": "up.is_active_90d", "label": "Активен за 90 дней"},
    "has_telegram": {"type": "bool", "column": "up.has_telegram", "label": "Есть Telegram"},
    "crm_type": {
        "type": "enum",
        "column": "up.crm_type",
        "label": "CRM-группа",
        "options": [
            {"value": "top", "label": "Лучшие"},
            {"value": "base", "label": "База"},
            {"value": "rare", "label": "Редкие"},
            {"value": "risk", "label": "Риск"},
            {"value": "dead", "label": "Давно без визита"},
            {"value": "lost", "label": "Потерянные"},
            {"value": "no_visits", "label": "Без визитов"},
        ],
    },
}

MESSAGE_VARIABLES = [
    {"key": "club_name", "label": "Название клуба", "token": "{club_name}", "description": "Название текущего клуба"},
    {"key": "first_name", "label": "Имя", "token": "{first_name}", "description": "Первое слово из ФИО"},
    {"key": "fio", "label": "ФИО", "token": "{fio}", "description": "Полное имя гостя"},
    {
        "key": "cm_bonus_balance",
        "label": "Баланс КБ",
        "token": "{cm_bonus_balance}",
        "description": "Текущий баланс КБ",
    },
    {
        "key": "token_balance",
        "label": "Баланс жетонов",
        "token": "{token_balance}",
        "description": "Текущий баланс жетонов",
    },
    {
        "key": "sessions_7d",
        "label": "Сессии за 7 дней",
        "token": "{sessions_7d}",
        "description": "Сырые Langame-сессии",
    },
    {
        "key": "sessions_30d",
        "label": "Сессии за 30 дней",
        "token": "{sessions_30d}",
        "description": "Сырые Langame-сессии",
    },
    {
        "key": "sessions_90d",
        "label": "Сессии за 90 дней",
        "token": "{sessions_90d}",
        "description": "Сырые Langame-сессии",
    },
]

ALLOWED_NUMBER_OPS = {"=", "!=", ">", ">=", "<", "<=", "between"}
ALLOWED_DATE_OPS = {"=", "!=", ">", ">=", "<", "<=", "between", "is_null", "is_not_null"}
ALLOWED_ENUM_OPS = {"=", "!=", "in", "not_in"}
ALLOWED_BOOL_OPS = {"="}

ALLOWED_EXTENSIONS = {
    "photo": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mov", ".mkv"},
    "animation": {".gif"},
    "document": {".pdf", ".doc", ".docx", ".txt", ".xlsx", ".xls", ".ppt", ".pptx"},
}


AUTO_MAILING_DEFAULTS = {
    "inactive_14_bonus": {
        "title": "Вернуть гостей после неактива",
        "description": "Автоматически отправляет сообщение гостям, которых не было в клубе заданное количество дней.",
        "message_text": (
            "Привет! Тебя давно не было в клубе 😔\n\n"
            "Мы начислили тебе 200 бонусов на 7 дней — приходи играть, будем ждать!"
        ),
        "days_inactive": 14,
        "bonus_amount": 200,
        "delay_minutes": None,
        "repeat_after_days": 30,
    },
    "first_visit_survey": {
        "title": "Опрос после первого визита",
        "description": "Через 20 минут после завершения первой сессии предлагает гостю пройти короткий опрос и получить бонусы.",
        "message_text": (
            "Спасибо за визит! 🙌\n\n"
            "Начислим еще 100 бонусов для твоего второго визита — "
            "ответь на два простых вопроса, это помогает нам стать лучше 😁"
        ),
        "days_inactive": 1,
        "bonus_amount": 100,
        "delay_minutes": 20,
        "repeat_after_days": 3650,
    },
    "streak_expiring_reminder": {
        "title": "Напоминание о стрике",
        "description": "За 3 дня до сгорания стрика 2+ дней напоминает гостю прийти ещё раз и получить жетоны для колеса.",
        "message_text": (
            "Привет! У тебя в {club_name} стрик из дней — {streak_days}. "
            "Приди еще раз до {date} и получи {next_reward} жетонов для колеса фортуны!"
        ),
        "days_inactive": 3,
        "bonus_amount": 1,
        "delay_minutes": None,
        "repeat_after_days": 7,
    },
}


def get_filter_fields() -> List[Dict[str, Any]]:
    result = []
    for key, meta in FILTER_FIELDS.items():
        item = {
            "key": key,
            "type": meta["type"],
            "label": meta["label"],
        }
        if "options" in meta:
            item["options"] = meta["options"]
        result.append(item)
    return result


def get_message_variables() -> List[Dict[str, Any]]:
    return [dict(item) for item in MESSAGE_VARIABLES]


def get_crm_segment_options(conn, club_id: int) -> List[Dict[str, Any]]:
    """Возвращает готовые CRM-группы для быстрых рассылок.

    count считается так же, как реальная рассылка: только гости текущего клуба
    с привязанным Telegram. Сами правила потом идут через общий механизм
    фильтров, поэтому CRM-группу можно комбинировать с другими условиями.
    """
    counts = {item["key"]: 0 for item in CRM_SEGMENT_OPTIONS}

    sql = """
        SELECT
            up.crm_type,
            COUNT(*) AS cnt
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        WHERE up.club_id = %s
          AND g.telegram_id IS NOT NULL
          AND up.crm_type IS NOT NULL
        GROUP BY up.crm_type
    """
    with conn.cursor() as cur:
        cur.execute(sql, (club_id,))
        rows = cur.fetchall()

    for row in rows:
        key = row.get("crm_type")
        if key in counts:
            counts[key] = int(row.get("cnt") or 0)

    result = []
    for item in CRM_SEGMENT_OPTIONS:
        result.append(
            {
                **item,
                "count": counts.get(item["key"], 0),
                "rules": {"rules": [{"field": "crm_type", "op": "=", "value": item["key"]}]},
            }
        )
    return result


PHONE_NORMALIZED_SQL = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
    "COALESCE(g.phone, ''), '+', ''), ' ', ''), '-', ''), '(', ''), ')', ''), '.', '')"
)


def _split_phone_values(value: Any) -> List[str]:
    """Парсит поле персональной рассылки: телефоны можно вводить через ;, запятую или перенос строки."""
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(_split_phone_values(item))
        return raw_items
    return [item.strip() for item in re.split(r"[;,\n]+", str(value)) if item.strip()]


def _phone_variants(raw_phone: str) -> List[str]:
    """Возвращает варианты номера для сопоставления с базой: 7999..., 8999..., 999..."""
    digits = re.sub(r"\D+", "", str(raw_phone or ""))
    if len(digits) < 7:
        return []

    variants = {digits}

    if len(digits) == 10:
        variants.add("7" + digits)
        variants.add("8" + digits)
    elif len(digits) == 11:
        variants.add(digits[-10:])
        if digits.startswith("8"):
            variants.add("7" + digits[1:])
        elif digits.startswith("7"):
            variants.add("8" + digits[1:])

    return [item for item in variants if item]


def _build_phone_rule(value: Any) -> Tuple[str, List[Any]]:
    variants: List[str] = []
    seen = set()

    for raw_phone in _split_phone_values(value):
        for variant in _phone_variants(raw_phone):
            if variant not in seen:
                seen.add(variant)
                variants.append(variant)

    if not variants:
        return "1 = 0", []

    placeholders = ", ".join(["%s"] * len(variants))
    return f"{PHONE_NORMALIZED_SQL} IN ({placeholders})", variants


def _build_single_rule(rule: Dict[str, Any]) -> Tuple[str, List[Any]]:
    field = rule.get("field")
    op = rule.get("op")
    value = rule.get("value")
    value_to = rule.get("value_to")

    if field not in FILTER_FIELDS:
        raise ValueError(f"Недопустимое поле фильтра: {field}")

    meta = FILTER_FIELDS[field]
    column = meta["column"]
    field_type = meta["type"]

    if field_type == "phone_list":
        if op not in {"=", "in"}:
            raise ValueError(f"Недопустимый оператор для {field}: {op}")
        return _build_phone_rule(value)

    if field_type == "number":
        if op not in ALLOWED_NUMBER_OPS:
            raise ValueError(f"Недопустимый оператор для {field}: {op}")
        if op == "between":
            return f"{column} BETWEEN %s AND %s", [value, value_to]
        return f"{column} {op} %s", [value]

    if field_type == "date":
        if op not in ALLOWED_DATE_OPS:
            raise ValueError(f"Недопустимый оператор для {field}: {op}")
        if op == "is_null":
            return f"{column} IS NULL", []
        if op == "is_not_null":
            return f"{column} IS NOT NULL", []
        if op == "between":
            return f"DATE({column}) BETWEEN %s AND %s", [value, value_to]
        return f"DATE({column}) {op} %s", [value]

    if field_type == "enum":
        if op not in ALLOWED_ENUM_OPS:
            raise ValueError(f"Недопустимый оператор для {field}: {op}")
        if op in {"in", "not_in"}:
            if not isinstance(value, list) or not value:
                raise ValueError(f"Для {field} оператор {op} требует непустой список")
            placeholders = ", ".join(["%s"] * len(value))
            sql_op = "IN" if op == "in" else "NOT IN"
            return f"{column} {sql_op} ({placeholders})", list(value)
        return f"{column} {op} %s", [value]

    if field_type == "bool":
        if op not in ALLOWED_BOOL_OPS:
            raise ValueError(f"Недопустимый оператор для {field}: {op}")
        return f"{column} = %s", [1 if str(value) in {"1", "true", "True"} else 0]

    raise ValueError(f"Неизвестный тип поля: {field_type}")


def build_where_clause(
    club_id: int, rules: List[Dict[str, Any]], require_telegram: bool = True
) -> Tuple[str, List[Any]]:
    where_parts = ["up.club_id = %s"]
    if require_telegram:
        where_parts.append("g.telegram_id IS NOT NULL")
    params: List[Any] = [club_id]

    for rule in rules:
        if not rule.get("field") or not rule.get("op"):
            continue
        sql_part, sql_params = _build_single_rule(rule)
        where_parts.append(sql_part)
        params.extend(sql_params)

    return " WHERE " + " AND ".join(where_parts), params


def preview_recipients_count(conn, club_id: int, rules: List[Dict[str, Any]]) -> int:
    where_sql, params = build_where_clause(club_id, rules)
    sql = f"""
        SELECT COUNT(DISTINCT up.guest_id) AS cnt
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        {where_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row["cnt"] or 0)


def _dedupe_recipient_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_guest: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        guest_id = row.get("guest_id")
        if guest_id is None:
            continue
        guest_id = int(guest_id)
        if guest_id not in by_guest:
            by_guest[guest_id] = row
    return list(by_guest.values())


def get_recipient_rows(conn, club_id: int, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        ensure_token_tables(cur)

    where_sql, params = build_where_clause(club_id, rules)
    sql = f"""
        SELECT
            up.guest_id,
            g.telegram_id,
            g.fio,
            c.name AS club_name,
            COALESCE(cbb.balance, 0) AS cm_bonus_balance,
            COALESCE(gwtb.balance, 0) AS token_balance,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs7
                WHERE gs7.club_id = up.club_id
                  AND gs7.guest_id = up.guest_id
                  AND gs7.date_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ) AS sessions_7d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs30
                WHERE gs30.club_id = up.club_id
                  AND gs30.guest_id = up.guest_id
                  AND gs30.date_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ) AS sessions_30d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs90
                WHERE gs90.club_id = up.club_id
                  AND gs90.guest_id = up.guest_id
                  AND gs90.date_start >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            ) AS sessions_90d
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        JOIN clubs c ON c.club_id = up.club_id
        LEFT JOIN cm_bonus_balances cbb
          ON cbb.club_id = up.club_id
         AND cbb.guest_id = up.guest_id
        LEFT JOIN guest_wheel_token_balances gwtb
          ON gwtb.club_id = up.club_id
         AND gwtb.guest_id = up.guest_id
        {where_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _dedupe_recipient_rows(cur.fetchall())


def get_recipient_rows_for_guest_ids(conn, club_id: int, guest_ids: List[int]) -> List[Dict[str, Any]]:
    guest_ids = sorted({int(guest_id) for guest_id in guest_ids if str(guest_id).strip().isdigit()})
    if not guest_ids:
        return []

    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        ensure_token_tables(cur)

    placeholders = ", ".join(["%s"] * len(guest_ids))
    sql = f"""
        SELECT
            g.guest_id,
            g.telegram_id,
            g.fio,
            c.name AS club_name,
            COALESCE(cbb.balance, 0) AS cm_bonus_balance,
            COALESCE(gwtb.balance, 0) AS token_balance,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs7
                WHERE gs7.club_id = g.club_id
                  AND gs7.guest_id = g.guest_id
                  AND gs7.date_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ) AS sessions_7d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs30
                WHERE gs30.club_id = g.club_id
                  AND gs30.guest_id = g.guest_id
                  AND gs30.date_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ) AS sessions_30d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs90
                WHERE gs90.club_id = g.club_id
                  AND gs90.guest_id = g.guest_id
                  AND gs90.date_start >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            ) AS sessions_90d
        FROM guests g
        JOIN clubs c ON c.club_id = g.club_id
        LEFT JOIN cm_bonus_balances cbb
          ON cbb.club_id = g.club_id
         AND cbb.guest_id = g.guest_id
        LEFT JOIN guest_wheel_token_balances gwtb
          ON gwtb.club_id = g.club_id
         AND gwtb.guest_id = g.guest_id
        WHERE g.club_id = %s
          AND g.guest_id IN ({placeholders})
          AND g.telegram_id IS NOT NULL
        ORDER BY FIELD(g.guest_id, {placeholders})
    """
    params = [club_id, *guest_ids, *guest_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _dedupe_recipient_rows(cur.fetchall())


def _looks_like_patronymic(value: str) -> bool:
    lower = (value or "").lower()
    return lower.endswith(("ич", "вна", "чна", "инична", "овна", "евна"))


def _looks_like_surname(value: str) -> bool:
    lower = (value or "").lower()
    return lower.endswith(
        ("ов", "ова", "ев", "ева", "ёв", "ёва", "ин", "ина", "ын", "ына", "ский", "ская", "цкий", "цкая")
    )


def _first_name(fio: str | None) -> str:
    value = (fio or "").strip()
    if not value:
        return ""
    parts = value.split()
    if len(parts) >= 3:
        if _looks_like_patronymic(parts[1]):
            return parts[0]
        if _looks_like_patronymic(parts[2]):
            return parts[1]
    if len(parts) == 2 and _looks_like_surname(parts[0]):
        return parts[1]
    return parts[0]


def _format_variable_value(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return str(int(value))
        return str(value.normalize())
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(round(value, 2))
    return str(value)


def render_message_template(message_text: str, recipient: Dict[str, Any]) -> str:
    values = {
        "fio": recipient.get("fio") or "",
        "club_name": recipient.get("club_name") or "",
        "name": _first_name(recipient.get("fio")),
        "first_name": _first_name(recipient.get("fio")),
        "cm_bonus_balance": recipient.get("cm_bonus_balance") or 0,
        "kb_balance": recipient.get("cm_bonus_balance") or 0,
        "token_balance": recipient.get("token_balance") or 0,
        "tokens_balance": recipient.get("token_balance") or 0,
        "sessions_7d": recipient.get("sessions_7d") or 0,
        "sessions_30d": recipient.get("sessions_30d") or 0,
        "sessions_90d": recipient.get("sessions_90d") or 0,
    }

    def replace(match):
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return _format_variable_value(values[key])

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, message_text or "")


def _ensure_table_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def _ensure_mailing_recipient_message_column(cursor) -> None:
    _ensure_table_column(cursor, "mailing_recipients", "message_text", "TEXT NULL AFTER telegram_id")


def list_segments(conn, club_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, club_id, name, rules_json, created_at, updated_at
        FROM saved_segments
        WHERE club_id = %s
        ORDER BY id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (club_id,))
        rows = cur.fetchall()

    for row in rows:
        if isinstance(row["rules_json"], str):
            row["rules_json"] = json.loads(row["rules_json"])
    return rows


def save_segment(conn, club_id: int, name: str, rules: List[Dict[str, Any]]) -> int:
    sql = """
        INSERT INTO saved_segments (club_id, name, rules_json)
        VALUES (%s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (club_id, name, json.dumps({"rules": rules}, ensure_ascii=False)))
        return cur.lastrowid


def delete_segment(conn, club_id: int, segment_id: int) -> None:
    sql = "DELETE FROM saved_segments WHERE id = %s AND club_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (segment_id, club_id))


def detect_file_type(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    for file_type, exts in ALLOWED_EXTENSIONS.items():
        if ext in exts:
            return file_type
    return "document"


def save_uploaded_file(file_storage, upload_dir: str) -> Dict[str, str]:
    os.makedirs(upload_dir, exist_ok=True)

    original_name = file_storage.filename or "file"
    safe_name = secure_filename(original_name)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    full_path = os.path.join(upload_dir, unique_name)
    file_storage.save(full_path)

    return {
        "original_name": original_name,
        "stored_name": unique_name,
        "file_path": full_path,
        "file_type": detect_file_type(original_name),
    }


def create_mailing(
    conn,
    club_id: int,
    segment_id: int | None,
    rules: List[Dict[str, Any]],
    message_text: str,
    parse_mode: str,
    attachments: List[Dict[str, str]],
) -> Dict[str, Any]:
    recipients = get_recipient_rows(conn, club_id, rules)
    recipients_count = len(recipients)

    with conn.cursor() as cur:
        _ensure_mailing_recipient_message_column(cur)
        cur.execute(
            """
            INSERT INTO mailings (
                club_id,
                segment_id,
                filters_json,
                message_text,
                parse_mode,
                status,
                recipients_count
            )
            VALUES (%s, %s, %s, %s, %s, 'queued', %s)
            """,
            (
                club_id,
                segment_id,
                json.dumps({"rules": rules}, ensure_ascii=False),
                message_text,
                parse_mode,
                recipients_count,
            ),
        )
        mailing_id = cur.lastrowid

        if attachments:
            cur.executemany(
                """
                INSERT INTO mailing_attachments (
                    mailing_id,
                    file_type,
                    file_path,
                    original_name
                )
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (
                        mailing_id,
                        item["file_type"],
                        item["file_path"],
                        item["original_name"],
                    )
                    for item in attachments
                ],
            )

        if recipients:
            cur.executemany(
                """
                INSERT INTO mailing_recipients (
                    mailing_id,
                    guest_id,
                    telegram_id,
                    message_text,
                    status
                )
                VALUES (%s, %s, %s, %s, 'pending')
                """,
                [
                    (
                        mailing_id,
                        row["guest_id"],
                        row["telegram_id"],
                        render_message_template(message_text, row),
                    )
                    for row in recipients
                ],
            )

    return {
        "mailing_id": mailing_id,
        "recipients_count": recipients_count,
    }


def list_mailings(conn, club_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            id,
            status,
            recipients_count,
            success_count,
            failed_count,
            created_at,
            started_at,
            finished_at
        FROM mailings
        WHERE club_id = %s
        ORDER BY id DESC
        LIMIT 50
    """
    with conn.cursor() as cur:
        cur.execute(sql, (club_id,))
        return cur.fetchall()


def _json_datetime(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _json_datetime(value) for key, value in dict(row or {}).items()}


def _format_minutes(minutes) -> str | None:
    if minutes is None:
        return None
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return None
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    rest = minutes % 60
    if rest:
        return f"{hours} ч {rest} мин"
    return f"{hours} ч"


def _format_hours(*, avg_hours) -> str | None:
    if avg_hours is None:
        return None
    try:
        hours_float = float(avg_hours)
    except (TypeError, ValueError):
        return None
    if hours_float < 24:
        return f"{round(hours_float, 1)} ч"
    days = hours_float / 24
    return f"{round(days, 1)} дн"


def _deduplicate_interaction_recipients(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse repeated recipient rows inside grouped auto-mailing campaigns."""
    best_by_guest: Dict[Any, Dict[str, Any]] = {}
    status_order = {"sent": 0, "pending": 1, "failed": 2}

    def choice_key(row: Dict[str, Any]):
        return (
            status_order.get(row.get("delivery_status"), 3),
            str(row.get("interaction_at") or ""),
            int(row.get("recipient_id") or 0),
        )

    for row in rows:
        key = row.get("guest_id") if row.get("guest_id") is not None else f"recipient-{row.get('recipient_id')}"
        current = best_by_guest.get(key)
        if current is None or choice_key(row) < choice_key(current):
            best_by_guest[key] = row

    return sorted(
        best_by_guest.values(),
        key=lambda row: (
            row.get("next_visit_at") is None,
            str(row.get("next_visit_at") or ""),
            int(row.get("recipient_id") or 0),
        ),
    )


def list_crm_interactions(conn, club_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_bonus_giveaway_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                CONCAT('mailing-', m.id) AS interaction_key,
                'mailing' AS interaction_type,
                m.id AS interaction_id,
                NULL AS giveaway_id,
                m.id AS mailing_id,
                m.status,
                0 AS bonus_amount,
                0 AS token_amount,
                m.recipients_count,
                m.success_count,
                m.failed_count,
                NULL AS awarded_count,
                NULL AS token_awarded_count,
                m.created_at
            FROM mailings m
            LEFT JOIN bonus_giveaways bg
              ON bg.club_id = m.club_id
             AND bg.mailing_id = m.id
            WHERE m.club_id = %s
              AND bg.id IS NULL
              AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) IS NULL

            UNION ALL

            SELECT
                CONCAT(
                    'auto-mailing-',
                    JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')),
                    '-',
                    DATE_FORMAT(MIN(m.created_at), '%%Y%%m%%d')
                ) AS interaction_key,
                'auto_mailing' AS interaction_type,
                MIN(m.id) AS interaction_id,
                NULL AS giveaway_id,
                MIN(m.id) AS mailing_id,
                CASE
                    WHEN MAX(m.status IN ('queued', 'in_progress')) > 0 THEN 'in_progress'
                    WHEN MAX(m.status = 'failed') > 0 THEN 'failed'
                    ELSE 'completed'
                END AS status,
                0 AS bonus_amount,
                0 AS token_amount,
                COUNT(DISTINCT mr.guest_id) AS recipients_count,
                COUNT(DISTINCT CASE WHEN mr.status = 'sent' THEN mr.guest_id END) AS success_count,
                COUNT(DISTINCT CASE WHEN mr.status = 'failed' THEN mr.guest_id END) AS failed_count,
                NULL AS awarded_count,
                NULL AS token_awarded_count,
                MIN(m.created_at) AS created_at
            FROM mailings m
            LEFT JOIN bonus_giveaways bg
              ON bg.club_id = m.club_id
             AND bg.mailing_id = m.id
            LEFT JOIN mailing_recipients mr
              ON mr.mailing_id = m.id
            WHERE m.club_id = %s
              AND bg.id IS NULL
              AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) IS NOT NULL
            GROUP BY
                JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')),
                DATE(m.created_at)

            UNION ALL

            SELECT
                CONCAT('giveaway-', bg.id) AS interaction_key,
                'giveaway' AS interaction_type,
                bg.id AS interaction_id,
                bg.id AS giveaway_id,
                bg.mailing_id,
                COALESCE(m.status, bg.status) AS status,
                bg.bonus_amount,
                bg.token_amount,
                bg.recipients_count,
                COALESCE(m.success_count, 0) AS success_count,
                COALESCE(m.failed_count, 0) AS failed_count,
                bg.awarded_count,
                bg.token_awarded_count,
                bg.created_at
            FROM bonus_giveaways bg
            LEFT JOIN mailings m
              ON m.club_id = bg.club_id
             AND m.id = bg.mailing_id
            WHERE bg.club_id = %s

            ORDER BY created_at DESC
            LIMIT %s
            """,
            (club_id, club_id, club_id, int(limit)),
        )
        return [_json_row(row) for row in cur.fetchall()]


def _get_interaction_base(conn, club_id: int, interaction_type: str, interaction_id: int) -> Dict[str, Any] | None:
    with conn.cursor() as cur:
        if interaction_type == "giveaway":
            ensure_bonus_giveaway_tables(conn)
            cur.execute(
                """
                SELECT
                    bg.id AS interaction_id,
                    'giveaway' AS interaction_type,
                    bg.id AS giveaway_id,
                    bg.mailing_id,
                    COALESCE(m.status, bg.status) AS status,
                    bg.bonus_amount,
                    bg.token_amount,
                    bg.message_text,
                    bg.recipients_count,
                    bg.awarded_count,
                    bg.token_awarded_count,
                    bg.skipped_count,
                    COALESCE(m.success_count, 0) AS success_count,
                    COALESCE(m.failed_count, 0) AS failed_count,
                    bg.created_at,
                    bg.finished_at
                FROM bonus_giveaways bg
                LEFT JOIN mailings m
                  ON m.club_id = bg.club_id
                 AND m.id = bg.mailing_id
                WHERE bg.club_id = %s
                  AND bg.id = %s
                LIMIT 1
                """,
                (club_id, interaction_id),
            )
        elif interaction_type == "auto_mailing":
            cur.execute(
                """
                SELECT
                    JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) AS auto_mailing_code,
                    DATE(m.created_at) AS group_date
                FROM mailings m
                LEFT JOIN bonus_giveaways bg
                  ON bg.club_id = m.club_id
                 AND bg.mailing_id = m.id
                WHERE m.club_id = %s
                  AND m.id = %s
                  AND bg.id IS NULL
                LIMIT 1
                """,
                (club_id, interaction_id),
            )
            group_ref = cur.fetchone()
            if not group_ref or not group_ref.get("auto_mailing_code"):
                return None
            cur.execute(
                """
                SELECT
                    MIN(m.id) AS interaction_id,
                    'auto_mailing' AS interaction_type,
                    NULL AS giveaway_id,
                    MIN(m.id) AS mailing_id,
                    CASE
                        WHEN MAX(m.status IN ('queued', 'in_progress')) > 0 THEN 'in_progress'
                        WHEN MAX(m.status = 'failed') > 0 THEN 'failed'
                        ELSE 'completed'
                    END AS status,
                    0 AS bonus_amount,
                    0 AS token_amount,
                    MIN(m.message_text) AS message_text,
                    COUNT(DISTINCT mr.guest_id) AS recipients_count,
                    NULL AS awarded_count,
                    NULL AS token_awarded_count,
                    NULL AS skipped_count,
                    COUNT(DISTINCT CASE WHEN mr.status = 'sent' THEN mr.guest_id END) AS success_count,
                    COUNT(DISTINCT CASE WHEN mr.status = 'failed' THEN mr.guest_id END) AS failed_count,
                    MIN(m.created_at) AS created_at,
                    MAX(m.finished_at) AS finished_at,
                    %s AS auto_mailing_code,
                    %s AS group_date
                FROM mailings m
                LEFT JOIN bonus_giveaways bg
                  ON bg.club_id = m.club_id
                 AND bg.mailing_id = m.id
                LEFT JOIN mailing_recipients mr
                  ON mr.mailing_id = m.id
                WHERE m.club_id = %s
                  AND bg.id IS NULL
                  AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) = %s
                  AND DATE(m.created_at) = %s
                """,
                (
                    group_ref.get("auto_mailing_code"),
                    group_ref.get("group_date"),
                    club_id,
                    group_ref.get("auto_mailing_code"),
                    group_ref.get("group_date"),
                ),
            )
        else:
            cur.execute(
                """
                SELECT
                    m.id AS interaction_id,
                    'mailing' AS interaction_type,
                    NULL AS giveaway_id,
                    m.id AS mailing_id,
                    m.status,
                    0 AS bonus_amount,
                    0 AS token_amount,
                    m.message_text,
                    m.recipients_count,
                    NULL AS awarded_count,
                    NULL AS token_awarded_count,
                    NULL AS skipped_count,
                    m.success_count,
                    m.failed_count,
                    m.created_at,
                    m.finished_at
                FROM mailings m
                LEFT JOIN bonus_giveaways bg
                  ON bg.club_id = m.club_id
                 AND bg.mailing_id = m.id
                WHERE m.club_id = %s
                  AND m.id = %s
                  AND bg.id IS NULL
                LIMIT 1
                """,
                (club_id, interaction_id),
            )
        return cur.fetchone()


def get_crm_interaction_detail(conn, club_id: int, interaction_type: str, interaction_id: int) -> Dict[str, Any] | None:
    if interaction_type not in {"mailing", "giveaway", "auto_mailing"}:
        return None

    ensure_bonus_giveaway_tables(conn)
    base = _get_interaction_base(conn, club_id, interaction_type, interaction_id)
    if not base:
        return None

    if interaction_type == "auto_mailing":
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id
                FROM mailings m
                LEFT JOIN bonus_giveaways bg
                  ON bg.club_id = m.club_id
                 AND bg.mailing_id = m.id
                WHERE m.club_id = %s
                  AND bg.id IS NULL
                  AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) = %s
                  AND DATE(m.created_at) = %s
                ORDER BY m.id ASC
                """,
                (club_id, base.get("auto_mailing_code"), base.get("group_date")),
            )
            mailing_ids = [row.get("id") for row in cur.fetchall() if row.get("id")]
    elif base.get("mailing_id"):
        mailing_ids = [base.get("mailing_id")]
    else:
        mailing_ids = []

    if not mailing_ids:
        recipients = []
    else:
        with conn.cursor() as cur:
            mailing_placeholders = ", ".join(["%s"] * len(mailing_ids))
            cur.execute(
                f"""
                SELECT
                    mr.id AS recipient_id,
                    mr.guest_id,
                    g.phone,
                    g.fio,
                    mr.status AS delivery_status,
                    mr.error_text,
                    mr.sent_at,
                    COALESCE(mr.sent_at, m.started_at, m.created_at) AS interaction_at,
                    up.crm_type,
                    up.total_visits,
                    up.avg_session_minutes,
                    (
                        SELECT COUNT(*)
                        FROM guest_sessions s30
                        WHERE s30.club_id = m.club_id
                          AND s30.guest_id = mr.guest_id
                          AND s30.date_start >= DATE_SUB(COALESCE(mr.sent_at, m.started_at, m.created_at), INTERVAL 30 DAY)
                          AND s30.date_start < COALESCE(mr.sent_at, m.started_at, m.created_at)
                    ) AS visits_30d_before_message,
                    ps.date_start AS previous_visit_at,
                    CASE
                        WHEN ps.date_start IS NOT NULL AND ps.date_stop IS NOT NULL
                        THEN TIMESTAMPDIFF(MINUTE, ps.date_start, ps.date_stop)
                        ELSE NULL
                    END AS previous_visit_minutes,
                    ns.date_start AS next_visit_at,
                    TIMESTAMPDIFF(HOUR, COALESCE(mr.sent_at, m.started_at, m.created_at), ns.date_start) AS next_visit_delay_hours,
                    CASE
                        WHEN ns.date_start IS NOT NULL AND ns.date_stop IS NOT NULL
                        THEN TIMESTAMPDIFF(MINUTE, ns.date_start, ns.date_stop)
                        ELSE NULL
                    END AS next_visit_minutes,
                    bgr.transaction_status AS bonus_status,
                    bgr.bonus_amount AS recipient_bonus_amount,
                    bgr.error_text AS bonus_error_text,
                    bgr.token_transaction_status AS token_status,
                    bgr.token_amount AS recipient_token_amount,
                    bgr.token_error_text
                FROM mailing_recipients mr
                JOIN mailings m
                  ON m.id = mr.mailing_id
                 AND m.club_id = %s
                LEFT JOIN guests g
                  ON g.club_id = m.club_id
                 AND g.guest_id = mr.guest_id
                LEFT JOIN user_portrait up
                  ON up.club_id = m.club_id
                 AND up.guest_id = mr.guest_id
                LEFT JOIN bonus_giveaway_recipients bgr
                  ON bgr.club_id = m.club_id
                 AND bgr.guest_id = mr.guest_id
                 AND bgr.giveaway_id = %s
                LEFT JOIN guest_sessions ps
                  ON ps.id = (
                    SELECT s.id
                    FROM guest_sessions s
                    WHERE s.club_id = m.club_id
                      AND s.guest_id = mr.guest_id
                      AND s.date_start < COALESCE(mr.sent_at, m.started_at, m.created_at)
                    ORDER BY s.date_start DESC
                    LIMIT 1
                  )
                LEFT JOIN guest_sessions ns
                  ON ns.id = (
                    SELECT s.id
                    FROM guest_sessions s
                    WHERE s.club_id = m.club_id
                      AND s.guest_id = mr.guest_id
                      AND s.date_start > COALESCE(mr.sent_at, m.started_at, m.created_at)
                      AND s.date_stop IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM guest_sessions prev
                          WHERE prev.club_id = s.club_id
                            AND prev.guest_id = s.guest_id
                            AND prev.date_start < s.date_start
                            AND prev.date_stop IS NOT NULL
                            AND s.date_start <= DATE_ADD(prev.date_stop, INTERVAL 2 HOUR)
                      )
                    ORDER BY s.date_start ASC
                    LIMIT 1
                  )
                WHERE mr.mailing_id IN ({mailing_placeholders})
                ORDER BY
                    CASE WHEN ns.date_start IS NULL THEN 1 ELSE 0 END,
                    ns.date_start ASC,
                    mr.id ASC
                LIMIT 300
                """,
                (club_id, base.get("giveaway_id"), *mailing_ids),
            )
            recipients = cur.fetchall()

    recipients = _deduplicate_interaction_recipients(recipients)
    sent_count = sum(1 for row in recipients if row.get("delivery_status") == "sent")
    failed_count = sum(1 for row in recipients if row.get("delivery_status") == "failed")
    pending_count = sum(1 for row in recipients if row.get("delivery_status") == "pending")
    returned_count = sum(1 for row in recipients if row.get("next_visit_at") is not None)
    returned_rows = [row for row in recipients if row.get("next_visit_at") is not None]
    returned_duration_rows = [row for row in returned_rows if row.get("next_visit_minutes") is not None]
    returned_delay_rows = [row for row in returned_rows if row.get("next_visit_delay_hours") is not None]
    avg_next_visit_minutes = (
        round(
            sum(int(row.get("next_visit_minutes") or 0) for row in returned_duration_rows) / len(returned_duration_rows)
        )
        if returned_duration_rows
        else None
    )
    avg_return_delay_hours = (
        round(
            sum(int(row.get("next_visit_delay_hours") or 0) for row in returned_delay_rows) / len(returned_delay_rows),
            1,
        )
        if returned_delay_rows
        else None
    )

    failure_reasons: Dict[str, int] = {}
    for row in recipients:
        if row.get("delivery_status") != "failed":
            continue
        reason = (row.get("error_text") or "Ошибка без текста").strip()
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    serialized_recipients = []
    for row in recipients:
        item = _json_row(row)
        item["avg_session_display"] = _format_minutes(row.get("avg_session_minutes"))
        item["previous_visit_duration_display"] = _format_minutes(row.get("previous_visit_minutes"))
        item["next_visit_duration_display"] = _format_minutes(row.get("next_visit_minutes"))
        item["next_visit_delay_display"] = _format_hours(avg_hours=row.get("next_visit_delay_hours"))
        serialized_recipients.append(item)

    return {
        "interaction": _json_row(base),
        "summary": {
            "recipients_count": int(base.get("recipients_count") or len(recipients)),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "returned_count": returned_count,
            "return_rate": round((returned_count / len(recipients)) * 100, 1) if recipients else 0,
            "not_returned_count": max(len(recipients) - returned_count, 0),
            "avg_next_visit_minutes": avg_next_visit_minutes,
            "avg_next_visit_duration_display": _format_minutes(avg_next_visit_minutes),
            "avg_return_delay_hours": avg_return_delay_hours,
            "avg_return_delay_display": _format_hours(avg_hours=avg_return_delay_hours),
            "failure_reasons": [
                {"reason": reason, "count": count}
                for reason, count in sorted(failure_reasons.items(), key=lambda item: item[1], reverse=True)
            ],
        },
        "recipients": serialized_recipients,
    }


CRM_CAMPAIGN_EFFECT_DAYS = 30


def _manual_campaign_sql() -> str:
    return """
        SELECT
            CONCAT('mailing-', m.id) AS campaign_key,
            'mailing' AS campaign_type,
            m.id AS campaign_id,
            NULL AS giveaway_id,
            m.id AS mailing_id,
            m.status,
            0 AS bonus_amount,
            0 AS token_amount,
            m.recipients_count,
            m.success_count,
            m.failed_count,
            m.message_text,
            m.created_at,
            m.finished_at
        FROM mailings m
        LEFT JOIN bonus_giveaways bg
          ON bg.club_id = m.club_id
         AND bg.mailing_id = m.id
        WHERE m.club_id = %s
          AND bg.id IS NULL
          AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(m.filters_json, '{}'), '$.auto_mailing')) IS NULL

        UNION ALL

        SELECT
            CONCAT('giveaway-', bg.id) AS campaign_key,
            'giveaway' AS campaign_type,
            bg.id AS campaign_id,
            bg.id AS giveaway_id,
            bg.mailing_id,
            COALESCE(m.status, bg.status) AS status,
            bg.bonus_amount,
            bg.token_amount,
            bg.recipients_count,
            COALESCE(m.success_count, 0) AS success_count,
            COALESCE(m.failed_count, 0) AS failed_count,
            bg.message_text,
            bg.created_at,
            bg.finished_at
        FROM bonus_giveaways bg
        LEFT JOIN mailings m
          ON m.club_id = bg.club_id
         AND m.id = bg.mailing_id
        WHERE bg.club_id = %s
          AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(bg.filters_json, '{}'), '$.auto_mailing')) IS NULL
    """


def _fetch_manual_campaign_base(
    conn,
    club_id: int,
    campaign_type: str,
    campaign_id: int,
) -> Dict[str, Any] | None:
    if campaign_type not in {"mailing", "giveaway"}:
        return None

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM ({_manual_campaign_sql()}) campaigns
            WHERE campaign_type = %s
              AND campaign_id = %s
            LIMIT 1
            """,
            (club_id, club_id, campaign_type, campaign_id),
        )
        return cur.fetchone()


def _campaign_mailing_ids(base: Dict[str, Any]) -> List[int]:
    mailing_id = base.get("mailing_id")
    return [int(mailing_id)] if mailing_id else []


def _fetch_campaign_effect_rows(
    conn,
    club_id: int,
    mailing_ids: List[int],
    giveaway_id: int | None,
) -> List[Dict[str, Any]]:
    if not mailing_ids:
        return []

    placeholders = ", ".join(["%s"] * len(mailing_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                mr.id AS recipient_id,
                mr.guest_id,
                g.phone,
                g.fio,
                mr.status AS delivery_status,
                mr.error_text,
                COALESCE(mr.sent_at, m.started_at, m.created_at) AS interaction_at,
                ns.date_start AS next_visit_at,
                CASE
                    WHEN ns.date_start IS NOT NULL
                    THEN TIMESTAMPDIFF(DAY, COALESCE(mr.sent_at, m.started_at, m.created_at), ns.date_start)
                    ELSE NULL
                END AS return_delay_days,
                CASE
                    WHEN ns.date_start IS NOT NULL AND ns.date_stop IS NOT NULL
                    THEN TIMESTAMPDIFF(MINUTE, ns.date_start, ns.date_stop)
                    ELSE NULL
                END AS next_visit_minutes,
                COALESCE((
                    SELECT SUM(gbt.amount)
                    FROM guest_balance_topups gbt
                    WHERE gbt.club_id = m.club_id
                      AND gbt.guest_id = mr.guest_id
                      AND gbt.amount > 0
                      AND gbt.amount <= %s
                      AND gbt.topup_at >= COALESCE(mr.sent_at, m.started_at, m.created_at)
                      AND gbt.topup_at < DATE_ADD(COALESCE(mr.sent_at, m.started_at, m.created_at), INTERVAL %s DAY)
                ), 0) AS topup_amount_after,
                COALESCE((
                    SELECT COUNT(*)
                    FROM guest_balance_topups gbt
                    WHERE gbt.club_id = m.club_id
                      AND gbt.guest_id = mr.guest_id
                      AND gbt.amount > 0
                      AND gbt.amount <= %s
                      AND gbt.topup_at >= COALESCE(mr.sent_at, m.started_at, m.created_at)
                      AND gbt.topup_at < DATE_ADD(COALESCE(mr.sent_at, m.started_at, m.created_at), INTERVAL %s DAY)
                ), 0) AS topups_after,
                COALESCE((
                    SELECT ABS(SUM(cbt.amount))
                    FROM cm_bonus_transactions cbt
                    WHERE cbt.club_id = m.club_id
                      AND cbt.guest_id = mr.guest_id
                      AND cbt.amount < 0
                      AND cbt.created_at >= COALESCE(mr.sent_at, m.started_at, m.created_at)
                      AND cbt.created_at < DATE_ADD(COALESCE(mr.sent_at, m.started_at, m.created_at), INTERVAL %s DAY)
                ), 0) AS used_bonus_after,
                bgr.bonus_amount AS recipient_bonus_amount,
                bgr.token_amount AS recipient_token_amount,
                bgr.transaction_status AS bonus_status,
                bgr.token_transaction_status AS token_status
            FROM mailing_recipients mr
            JOIN mailings m
              ON m.id = mr.mailing_id
             AND m.club_id = %s
            LEFT JOIN guests g
              ON g.club_id = m.club_id
             AND g.guest_id = mr.guest_id
            LEFT JOIN bonus_giveaway_recipients bgr
              ON bgr.club_id = m.club_id
             AND bgr.guest_id = mr.guest_id
             AND bgr.giveaway_id = %s
            LEFT JOIN guest_sessions ns
              ON ns.id = (
                SELECT s.id
                FROM guest_sessions s
                WHERE s.club_id = m.club_id
                  AND s.guest_id = mr.guest_id
                  AND s.date_start > COALESCE(mr.sent_at, m.started_at, m.created_at)
                  AND s.date_stop IS NOT NULL
                  AND s.date_start < DATE_ADD(COALESCE(mr.sent_at, m.started_at, m.created_at), INTERVAL %s DAY)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM guest_sessions prev
                      WHERE prev.club_id = s.club_id
                        AND prev.guest_id = s.guest_id
                        AND prev.date_start < s.date_start
                        AND prev.date_stop IS NOT NULL
                        AND s.date_start <= DATE_ADD(prev.date_stop, INTERVAL 2 HOUR)
                  )
                ORDER BY s.date_start ASC
                LIMIT 1
              )
            WHERE mr.mailing_id IN ({placeholders})
            ORDER BY
                CASE WHEN ns.date_start IS NULL THEN 1 ELSE 0 END,
                ns.date_start ASC,
                mr.id ASC
            """,
            (
                BALANCE_TOPUP_MAX_AMOUNT,
                CRM_CAMPAIGN_EFFECT_DAYS,
                BALANCE_TOPUP_MAX_AMOUNT,
                CRM_CAMPAIGN_EFFECT_DAYS,
                CRM_CAMPAIGN_EFFECT_DAYS,
                club_id,
                giveaway_id,
                CRM_CAMPAIGN_EFFECT_DAYS,
                *mailing_ids,
            ),
        )
        return cur.fetchall()


def _dedupe_campaign_effect_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_guest: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        guest_id = row.get("guest_id")
        if guest_id is None:
            continue

        guest_id = int(guest_id)
        current = by_guest.setdefault(guest_id, dict(row))
        current["delivery_status"] = (
            "sent"
            if "sent" in {current.get("delivery_status"), row.get("delivery_status")}
            else (
                "failed"
                if "failed" in {current.get("delivery_status"), row.get("delivery_status")}
                else current.get("delivery_status")
            )
        )

        if current.get("next_visit_at") is None or (
            row.get("next_visit_at") is not None and row.get("next_visit_at") < current.get("next_visit_at")
        ):
            current["next_visit_at"] = row.get("next_visit_at")
            current["return_delay_days"] = row.get("return_delay_days")
            current["next_visit_minutes"] = row.get("next_visit_minutes")

        current["topup_amount_after"] = max(
            float(current.get("topup_amount_after") or 0),
            float(row.get("topup_amount_after") or 0),
        )
        current["topups_after"] = max(int(current.get("topups_after") or 0), int(row.get("topups_after") or 0))
        current["used_bonus_after"] = max(
            float(current.get("used_bonus_after") or 0),
            float(row.get("used_bonus_after") or 0),
        )
        if row.get("bonus_status") == "awarded":
            current["bonus_status"] = "awarded"
        if row.get("token_status") == "awarded":
            current["token_status"] = "awarded"

    return list(by_guest.values())


def _campaign_effect_summary(base: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    unique_rows = _dedupe_campaign_effect_rows(rows)
    recipients_count = max(int(base.get("recipients_count") or 0), len(unique_rows))
    delivered_count = sum(1 for row in unique_rows if row.get("delivery_status") == "sent")
    failed_count = sum(1 for row in unique_rows if row.get("delivery_status") == "failed")
    visited_count = sum(1 for row in unique_rows if row.get("next_visit_at") is not None)
    topped_up_count = sum(1 for row in unique_rows if float(row.get("topup_amount_after") or 0) > 0)
    topup_amount = sum(float(row.get("topup_amount_after") or 0) for row in unique_rows)
    used_bonus = sum(float(row.get("used_bonus_after") or 0) for row in unique_rows)
    bonus_spent = int(base.get("bonus_amount") or 0) * sum(
        1 for row in unique_rows if row.get("bonus_status") == "awarded"
    )
    token_spent = int(base.get("token_amount") or 0) * sum(
        1 for row in unique_rows if row.get("token_status") == "awarded"
    )
    bonus_denominator = used_bonus or bonus_spent

    return {
        "window_days": CRM_CAMPAIGN_EFFECT_DAYS,
        "recipients_count": recipients_count,
        "delivered_count": delivered_count,
        "failed_count": failed_count,
        "visited_count": visited_count,
        "topped_up_count": topped_up_count,
        "bonus_spent": bonus_spent,
        "token_spent": token_spent,
        "used_bonus": round(used_bonus, 2),
        "topup_amount": round(topup_amount, 2),
        "visit_conversion": round(visited_count / recipients_count * 100, 1) if recipients_count else 0,
        "topup_conversion": round(topped_up_count / recipients_count * 100, 1) if recipients_count else 0,
        "avg_topup": round(topup_amount / topped_up_count, 2) if topped_up_count else 0,
        "topup_per_bonus": round(topup_amount / bonus_denominator, 2) if bonus_denominator else 0,
    }


def _return_delay_funnel(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets = [
        ("0", "В день отправки", 0, 0),
        ("1", "На следующий день", 1, 1),
        ("2-3", "2-3 дня", 2, 3),
        ("4-7", "4-7 дней", 4, 7),
        ("8-14", "8-14 дней", 8, 14),
        ("15-30", "15-30 дней", 15, 30),
    ]
    result = []
    max_count = 1
    counts = []
    for key, label, min_days, max_days in buckets:
        count = sum(
            1
            for row in rows
            if row.get("return_delay_days") is not None
            and min_days <= int(row.get("return_delay_days") or 0) <= max_days
        )
        counts.append((key, label, count))
        max_count = max(max_count, count)
    for key, label, count in counts:
        result.append({"key": key, "label": label, "count": count, "height": max(8, round(count / max_count * 100))})
    return result


def list_manual_crm_campaigns(conn, club_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    ensure_bonus_giveaway_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM ({_manual_campaign_sql()}) campaigns
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (club_id, club_id, int(limit)),
        )
        rows = cur.fetchall()

    campaigns = []
    for row in rows:
        mailing_ids = _campaign_mailing_ids(row)
        effect_rows = _fetch_campaign_effect_rows(conn, club_id, mailing_ids, row.get("giveaway_id"))
        item = _json_row(row)
        item["summary"] = _campaign_effect_summary(row, effect_rows)
        campaigns.append(item)
    return campaigns


def get_manual_crm_campaign_passport(
    conn,
    club_id: int,
    campaign_type: str,
    campaign_id: int,
) -> Dict[str, Any] | None:
    ensure_bonus_giveaway_tables(conn)
    base = _fetch_manual_campaign_base(conn, club_id, campaign_type, campaign_id)
    if not base:
        return None

    detail = get_crm_interaction_detail(conn, club_id, campaign_type, campaign_id)
    if not detail:
        return None

    mailing_ids = _campaign_mailing_ids(base)
    effect_rows = _fetch_campaign_effect_rows(conn, club_id, mailing_ids, base.get("giveaway_id"))
    unique_effect_rows = _dedupe_campaign_effect_rows(effect_rows)
    effect_by_guest = {int(row.get("guest_id")): row for row in unique_effect_rows if row.get("guest_id")}
    summary = _campaign_effect_summary(base, effect_rows)

    recipients = []
    seen_guest_ids = set()
    for row in detail.get("recipients", []):
        guest_id = int(row.get("guest_id") or 0)
        if guest_id and guest_id in seen_guest_ids:
            continue
        if guest_id:
            seen_guest_ids.add(guest_id)
        effect = effect_by_guest.get(guest_id, {})
        item = dict(row)
        item["topups_after"] = int(effect.get("topups_after") or 0)
        item["topup_amount_after"] = round(float(effect.get("topup_amount_after") or 0), 2)
        item["used_bonus_after"] = round(float(effect.get("used_bonus_after") or 0), 2)
        item["return_delay_days"] = effect.get("return_delay_days")
        item["converted"] = bool(item["topup_amount_after"] > 0)
        recipients.append(item)

    delivered_count = summary["delivered_count"]
    visited_count = summary["visited_count"]
    funnel_max = max(summary["recipients_count"], delivered_count, visited_count, 1)

    return {
        "campaign": _json_row(base),
        "summary": summary,
        "delivery_funnel": [
            {
                "label": "Получателей",
                "count": summary["recipients_count"],
                "height": round(summary["recipients_count"] / funnel_max * 100),
            },
            {
                "label": "Доставлено",
                "count": delivered_count,
                "height": max(8, round(delivered_count / funnel_max * 100)),
            },
            {"label": "С визитом", "count": visited_count, "height": max(8, round(visited_count / funnel_max * 100))},
        ],
        "return_funnel": _return_delay_funnel(unique_effect_rows),
        "recipients": recipients,
        "message_text": detail.get("interaction", {}).get("message_text") or base.get("message_text") or "",
    }


def _ensure_auto_mailing_column(cursor, column_name: str, ddl: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'auto_mailing_settings'
          AND COLUMN_NAME = %s
        """,
        (column_name,),
    )
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute(f"ALTER TABLE auto_mailing_settings ADD COLUMN {column_name} {ddl}")


def ensure_auto_mailings(conn, club_id: int) -> None:
    """Создаёт и обновляет настройки авторассылок для клуба лениво."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auto_mailing_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                code VARCHAR(80) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                message_text TEXT NOT NULL,
                days_inactive INT NOT NULL DEFAULT 14,
                bonus_amount INT NOT NULL DEFAULT 200,
                delay_minutes INT NULL,
                repeat_after_days INT NOT NULL DEFAULT 30,
                is_enabled TINYINT(1) NOT NULL DEFAULT 0,
                last_run_at DATETIME NULL,
                last_mailing_id INT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_auto_mailing_club_code (club_id, code),
                KEY idx_auto_mailing_enabled (is_enabled),
                KEY idx_auto_mailing_club (club_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        _ensure_auto_mailing_column(cur, "days_inactive", "INT NOT NULL DEFAULT 14")
        _ensure_auto_mailing_column(cur, "bonus_amount", "INT NOT NULL DEFAULT 200")
        _ensure_auto_mailing_column(cur, "delay_minutes", "INT NULL")
        _ensure_auto_mailing_column(cur, "repeat_after_days", "INT NOT NULL DEFAULT 30")
        _ensure_auto_mailing_column(cur, "last_run_at", "DATETIME NULL")
        _ensure_auto_mailing_column(cur, "last_mailing_id", "INT NULL")

        for code, defaults in AUTO_MAILING_DEFAULTS.items():
            cur.execute(
                """
                INSERT INTO auto_mailing_settings (
                    club_id,
                    code,
                    title,
                    description,
                    message_text,
                    days_inactive,
                    bonus_amount,
                    delay_minutes,
                    repeat_after_days,
                    is_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE
                    id = id
                """,
                (
                    club_id,
                    code,
                    defaults["title"],
                    defaults["description"],
                    defaults["message_text"],
                    defaults["days_inactive"],
                    defaults["bonus_amount"],
                    defaults.get("delay_minutes"),
                    defaults["repeat_after_days"],
                ),
            )


def list_auto_mailings(conn, club_id: int):
    ensure_auto_mailings(conn, club_id)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                code,
                title,
                description,
                message_text,
                days_inactive,
                bonus_amount,
                delay_minutes,
                repeat_after_days,
                is_enabled,
                last_run_at,
                last_mailing_id,
                updated_at
            FROM auto_mailing_settings
            WHERE club_id = %s
            ORDER BY id ASC
            """,
            (club_id,),
        )
        return cur.fetchall()


def update_auto_mailing_enabled(conn, club_id: int, code: str, is_enabled: bool) -> bool:
    return update_auto_mailing_settings(conn, club_id, code, is_enabled=is_enabled) is not None


def update_auto_mailing_settings(
    conn,
    club_id: int,
    code: str,
    is_enabled: bool | None = None,
    days_inactive: int | None = None,
    bonus_amount: int | None = None,
    delay_minutes: int | None = None,
    title: str | None = None,
    description: str | None = None,
    message_text: str | None = None,
) -> Dict[str, Any] | None:
    """Обновляет настройки авторассылки и возвращает актуальную запись."""
    ensure_auto_mailings(conn, club_id)

    fields = []
    params = []

    if is_enabled is not None:
        fields.append("is_enabled = %s")
        params.append(1 if is_enabled else 0)

    if days_inactive is not None:
        days_inactive = max(int(days_inactive or 0), 1)
        fields.append("days_inactive = %s")
        params.append(days_inactive)

    if delay_minutes is not None:
        delay_minutes = max(int(delay_minutes or 0), 1)
        fields.append("delay_minutes = %s")
        params.append(delay_minutes)

    if bonus_amount is not None:
        bonus_amount = max(int(bonus_amount or 0), 1)
        fields.append("bonus_amount = %s")
        params.append(bonus_amount)

    if title is not None:
        fields.append("title = %s")
        params.append(title.strip()[:255])

    if description is not None:
        fields.append("description = %s")
        params.append(description.strip())

    if message_text is not None:
        fields.append("message_text = %s")
        params.append(message_text.strip())

    if not fields:
        fields.append("updated_at = NOW()")
    else:
        fields.append("updated_at = NOW()")

    params.extend([club_id, code])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE auto_mailing_settings
            SET {', '.join(fields)}
            WHERE club_id = %s
              AND code = %s
            """,
            tuple(params),
        )
        if cur.rowcount == 0:
            return None

        cur.execute(
            """
            SELECT
                id,
                code,
                title,
                description,
                message_text,
                days_inactive,
                bonus_amount,
                delay_minutes,
                repeat_after_days,
                is_enabled,
                last_run_at,
                last_mailing_id,
                updated_at
            FROM auto_mailing_settings
            WHERE club_id = %s AND code = %s
            LIMIT 1
            """,
            (club_id, code),
        )
        return cur.fetchone()


def get_inactive_auto_mailing_recipients(
    conn,
    club_id: int,
    automation_code: str,
    days_inactive: int = 14,
    repeat_after_days: int = 30,
) -> List[Dict[str, Any]]:
    """Получатели авторассылки: были в клубе давно и не получали эту авторассылку недавно."""
    sql = """
        SELECT
            up.guest_id,
            g.telegram_id,
            g.fio,
            c.name AS club_name,
            COALESCE(cbb.balance, 0) AS cm_bonus_balance,
            COALESCE(gwtb.balance, 0) AS token_balance,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs7
                WHERE gs7.club_id = up.club_id
                  AND gs7.guest_id = up.guest_id
                  AND gs7.date_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ) AS sessions_7d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs30
                WHERE gs30.club_id = up.club_id
                  AND gs30.guest_id = up.guest_id
                  AND gs30.date_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ) AS sessions_30d,
            (
                SELECT COUNT(*)
                FROM guest_sessions gs90
                WHERE gs90.club_id = up.club_id
                  AND gs90.guest_id = up.guest_id
                  AND gs90.date_start >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            ) AS sessions_90d
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        JOIN clubs c ON c.club_id = up.club_id
        LEFT JOIN cm_bonus_balances cbb
          ON cbb.club_id = up.club_id
         AND cbb.guest_id = up.guest_id
        LEFT JOIN guest_wheel_token_balances gwtb
          ON gwtb.club_id = up.club_id
         AND gwtb.guest_id = up.guest_id
        WHERE up.club_id = %s
          AND g.telegram_id IS NOT NULL
          AND up.days_since_last_visit >= %s
          AND NOT EXISTS (
              SELECT 1
              FROM auto_mailing_logs aml
              WHERE aml.club_id = up.club_id
                AND aml.automation_code = %s
                AND aml.guest_id = up.guest_id
                AND aml.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
          )
    """
    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        ensure_token_tables(cur)
        cur.execute(sql, (club_id, days_inactive, automation_code, repeat_after_days))
        return cur.fetchall()


def create_mailing_for_recipients(
    conn,
    club_id: int,
    recipients: List[Dict[str, Any]],
    message_text: str,
    parse_mode: str = "HTML",
    filters_json: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    recipients_count = len(recipients)

    with conn.cursor() as cur:
        _ensure_mailing_recipient_message_column(cur)
        cur.execute(
            """
            INSERT INTO mailings (
                club_id,
                segment_id,
                filters_json,
                message_text,
                parse_mode,
                status,
                recipients_count
            )
            VALUES (%s, NULL, %s, %s, %s, 'queued', %s)
            """,
            (
                club_id,
                json.dumps(filters_json or {}, ensure_ascii=False),
                message_text,
                parse_mode,
                recipients_count,
            ),
        )
        mailing_id = cur.lastrowid

        if recipients:
            cur.executemany(
                """
                INSERT INTO mailing_recipients (
                    mailing_id,
                    guest_id,
                    telegram_id,
                    message_text,
                    status
                )
                VALUES (%s, %s, %s, %s, 'pending')
                """,
                [
                    (
                        mailing_id,
                        row["guest_id"],
                        row["telegram_id"],
                        render_message_template(message_text, row),
                    )
                    for row in recipients
                ],
            )

    return {
        "mailing_id": mailing_id,
        "recipients_count": recipients_count,
    }


def ensure_bonus_giveaway_tables(conn) -> None:
    """Создаёт таблицы раздач бонусов лениво.

    Раздача — это массовое начисление КБ выбранной аудитории + Telegram-уведомление.
    """
    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        ensure_token_tables(cur)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bonus_giveaways (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                filters_json JSON NULL,
                bonus_amount INT NOT NULL,
                token_amount INT NOT NULL DEFAULT 0,
                message_text TEXT NOT NULL,
                mailing_id INT NULL,
                status VARCHAR(40) NOT NULL DEFAULT 'created',
                recipients_count INT NOT NULL DEFAULT 0,
                awarded_count INT NOT NULL DEFAULT 0,
                token_awarded_count INT NOT NULL DEFAULT 0,
                skipped_count INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME NULL,
                KEY idx_bonus_giveaways_club_created (club_id, created_at),
                KEY idx_bonus_giveaways_mailing (mailing_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bonus_giveaway_recipients (
                id INT AUTO_INCREMENT PRIMARY KEY,
                giveaway_id INT NOT NULL,
                club_id INT NOT NULL,
                guest_id INT NOT NULL,
                telegram_id BIGINT NULL,
                bonus_amount INT NOT NULL,
                token_amount INT NOT NULL DEFAULT 0,
                transaction_status VARCHAR(40) NOT NULL DEFAULT 'pending',
                token_transaction_status VARCHAR(40) NOT NULL DEFAULT 'pending',
                transaction_id INT NULL,
                token_transaction_id INT NULL,
                mailing_recipient_id INT NULL,
                error_text TEXT NULL,
                token_error_text TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                awarded_at DATETIME NULL,
                UNIQUE KEY uq_bonus_giveaway_guest (giveaway_id, club_id, guest_id),
                KEY idx_bonus_giveaway_recipients_guest (club_id, guest_id),
                KEY idx_bonus_giveaway_recipients_status (transaction_status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        _ensure_table_column(cur, "bonus_giveaways", "token_amount", "INT NOT NULL DEFAULT 0 AFTER bonus_amount")
        _ensure_table_column(
            cur, "bonus_giveaways", "token_awarded_count", "INT NOT NULL DEFAULT 0 AFTER awarded_count"
        )
        _ensure_table_column(cur, "bonus_giveaways", "is_expiring", "TINYINT(1) NOT NULL DEFAULT 0 AFTER token_amount")
        _ensure_table_column(cur, "bonus_giveaways", "expires_after_seconds", "INT NULL AFTER is_expiring")
        _ensure_table_column(cur, "bonus_giveaways", "expires_at", "DATETIME NULL AFTER expires_after_seconds")
        _ensure_table_column(
            cur, "bonus_giveaway_recipients", "token_amount", "INT NOT NULL DEFAULT 0 AFTER bonus_amount"
        )
        _ensure_table_column(cur, "bonus_giveaway_recipients", "expires_at", "DATETIME NULL AFTER token_amount")
        _ensure_table_column(
            cur,
            "bonus_giveaway_recipients",
            "token_transaction_status",
            "VARCHAR(40) NOT NULL DEFAULT 'pending' AFTER transaction_status",
        )
        _ensure_table_column(cur, "bonus_giveaway_recipients", "token_transaction_id", "INT NULL AFTER transaction_id")
        _ensure_table_column(cur, "bonus_giveaway_recipients", "token_error_text", "TEXT NULL AFTER error_text")
        cur.execute("""
            SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'bonus_giveaway_recipients'
              AND INDEX_NAME = 'uq_bonus_giveaway_guest'
            """)
        idx = cur.fetchone() or {}
        if (idx.get("cols") or "") == "giveaway_id,guest_id":
            cur.execute("""
                ALTER TABLE bonus_giveaway_recipients
                DROP INDEX uq_bonus_giveaway_guest,
                ADD UNIQUE KEY uq_bonus_giveaway_guest (giveaway_id, club_id, guest_id)
                """)


def list_bonus_giveaways(conn, club_id: int) -> List[Dict[str, Any]]:
    ensure_bonus_giveaway_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                bonus_amount,
                token_amount,
                is_expiring,
                expires_after_seconds,
                expires_at,
                status,
                recipients_count,
                awarded_count,
                token_awarded_count,
                skipped_count,
                mailing_id,
                created_at,
                finished_at
            FROM bonus_giveaways
            WHERE club_id = %s
            ORDER BY id DESC
            LIMIT 20
            """,
            (club_id,),
        )
        return cur.fetchall()


def create_bonus_giveaway(
    conn,
    club_id: int,
    rules: List[Dict[str, Any]],
    bonus_amount: int,
    message_text: str,
    token_amount: int = 0,
    is_expiring: bool = False,
    expires_after_seconds: int | None = None,
    parse_mode: str = "HTML",
    recipient_rows: List[Dict[str, Any]] | None = None,
    filters_json_extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Начисляет КБ/жетоны выбранной аудитории и создаёт Telegram-рассылку.

    Фильтры используются ровно те же, что и в сегментах/ручной рассылке.
    Возвращает id раздачи, id рассылки и количество получателей.
    """
    bonus_amount = int(bonus_amount or 0)
    token_amount = int(token_amount or 0)
    if bonus_amount < 0:
        raise ValueError("Количество бонусов не может быть отрицательным")
    if token_amount < 0:
        raise ValueError("Количество жетонов не может быть отрицательным")
    if bonus_amount <= 0 and token_amount <= 0:
        raise ValueError("Укажи бонусы или жетоны больше 0")
    if is_expiring and bonus_amount <= 0:
        raise ValueError("Сгорающий бонус можно включить только для раздачи КБ")
    if is_expiring:
        expires_after_seconds = int(expires_after_seconds or 0)
        if expires_after_seconds <= 0:
            raise ValueError("Укажи срок сгорания бонуса")
    else:
        expires_after_seconds = None

    message_text = (message_text or "").strip()
    if not message_text:
        raise ValueError("Сообщение раздачи пустое")

    ensure_bonus_giveaway_tables(conn)
    recipients = list(recipient_rows) if recipient_rows is not None else get_recipient_rows(conn, club_id, rules)
    recipients_count = len(recipients)
    expires_at = (
        datetime.utcnow() + timedelta(seconds=expires_after_seconds) if is_expiring and expires_after_seconds else None
    )
    filters_json = {
        "rules": rules,
        "type": "bonus_giveaway",
        "bonus_amount": bonus_amount,
        "token_amount": token_amount,
        "is_expiring": bool(is_expiring),
        "expires_after_seconds": expires_after_seconds,
    }
    if filters_json_extra:
        filters_json.update(filters_json_extra)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bonus_giveaways (
                club_id,
                filters_json,
                bonus_amount,
                token_amount,
                is_expiring,
                expires_after_seconds,
                expires_at,
                message_text,
                status,
                recipients_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'processing', %s)
            """,
            (
                club_id,
                json.dumps(filters_json, ensure_ascii=False),
                bonus_amount,
                token_amount,
                1 if is_expiring else 0,
                expires_after_seconds,
                expires_at,
                message_text,
                recipients_count,
            ),
        )
        giveaway_id = cur.lastrowid

        awarded_count = 0
        token_awarded_count = 0
        skipped_count = 0
        for row in recipients:
            guest_id = int(row["guest_id"])
            telegram_id = row.get("telegram_id")
            error_text = None
            token_error_text = None
            status = "skipped" if bonus_amount <= 0 else "awarded"
            token_status = "skipped" if token_amount <= 0 else "awarded"

            if bonus_amount > 0:
                try:
                    awarded = add_cm_bonus_transaction(
                        cursor=cur,
                        guest_id=guest_id,
                        club_id=club_id,
                        amount=bonus_amount,
                        source_type="bonus_giveaway",
                        source_id=str(giveaway_id),
                        description=f"Раздача бонусов #{giveaway_id}",
                        status="done",
                        expires_at=expires_at,
                    )
                    if awarded:
                        awarded_count += 1
                        row["cm_bonus_balance"] = int(row.get("cm_bonus_balance") or 0) + bonus_amount
                    else:
                        status = "skipped"
                        error_text = "Дубликат операции"
                except Exception as exc:
                    status = "failed"
                    error_text = str(exc)[:1000]

            if token_amount > 0:
                try:
                    token_awarded = _add_token_transaction(
                        cursor=cur,
                        guest_id=guest_id,
                        club_id=club_id,
                        amount=token_amount,
                        source_type="bonus_giveaway",
                        source_id=str(giveaway_id),
                        description=f"Раздача жетонов #{giveaway_id}",
                    )
                    if token_awarded:
                        token_awarded_count += 1
                        row["token_balance"] = int(row.get("token_balance") or 0) + token_amount
                    else:
                        token_status = "skipped"
                        token_error_text = "Дубликат операции"
                except Exception as exc:
                    token_status = "failed"
                    token_error_text = str(exc)[:1000]

            bonus_problem = bonus_amount > 0 and status != "awarded"
            token_problem = token_amount > 0 and token_status != "awarded"
            if bonus_problem or token_problem:
                skipped_count += 1

            cur.execute(
                """
                INSERT INTO bonus_giveaway_recipients (
                    giveaway_id,
                    club_id,
                    guest_id,
                    telegram_id,
                    bonus_amount,
                    token_amount,
                    expires_at,
                    transaction_status,
                    token_transaction_status,
                    error_text,
                    token_error_text,
                    awarded_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, IF(%s = 'awarded' OR %s = 'awarded', NOW(), NULL))
                """,
                (
                    giveaway_id,
                    club_id,
                    guest_id,
                    telegram_id,
                    bonus_amount,
                    token_amount,
                    expires_at if status == "awarded" else None,
                    status,
                    token_status,
                    error_text,
                    token_error_text,
                    status,
                    token_status,
                ),
            )

    mailing = create_mailing_for_recipients(
        conn=conn,
        club_id=club_id,
        recipients=recipients,
        message_text=message_text,
        parse_mode=parse_mode,
        filters_json=filters_json,
    )
    mailing_id = mailing["mailing_id"]

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bonus_giveaways
            SET mailing_id = %s,
                status = 'completed',
                awarded_count = %s,
                token_awarded_count = %s,
                skipped_count = %s,
                finished_at = NOW()
            WHERE id = %s AND club_id = %s
            """,
            (mailing_id, awarded_count, token_awarded_count, skipped_count, giveaway_id, club_id),
        )

    return {
        "giveaway_id": giveaway_id,
        "mailing_id": mailing_id,
        "recipients_count": recipients_count,
        "awarded_count": awarded_count,
        "token_awarded_count": token_awarded_count,
        "skipped_count": skipped_count,
        "bonus_amount": bonus_amount,
        "token_amount": token_amount,
        "is_expiring": bool(is_expiring),
        "expires_at": expires_at,
    }
