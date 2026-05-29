import json
import os
import re
import uuid
from typing import Any, Dict, List, Tuple

from werkzeug.utils import secure_filename

from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables

AUTO_MAILING_DEFAULTS = {
    "inactive_14_bonus": {
        "title": "Вернуть гостей после неактива",
        "description": "Автоматически отправляет сообщение гостям, которых не было в клубе заданное количество дней.",
        "message_text": (
            "Привет! Тебя давно не было в клубе 😔\n\n"
            "Мы начислили тебе 200 бонусов — приходи играть, будем ждать!"
        ),
        "days_inactive": 14,
        "bonus_amount": 200,
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
        "repeat_after_days": 3650,
    },
}

CRM_SEGMENT_OPTIONS = [
    {"key": "top", "label": "TOP", "title": "Топ-гости", "emoji": "👑", "description": "15+ визитов за 90 дней"},
    {"key": "base", "label": "BASE", "title": "База", "emoji": "👥", "description": "10–14 визитов за 90 дней"},
    {"key": "rare", "label": "RARE", "title": "Редкие", "emoji": "✨", "description": "1–9 визитов, были недавно"},
    {"key": "risk", "label": "RISK", "title": "В зоне риска", "emoji": "⚠️", "description": "Не были 14–29 дней"},
    {"key": "lost", "label": "LOST", "title": "Потерянные", "emoji": "💔", "description": "Не были 30–89 дней"},
    {"key": "dead", "label": "DEAD", "title": "Мёртвая база", "emoji": "☠️", "description": "Не были 90+ дней"},
    {"key": "no_visits", "label": "NO VISITS", "title": "Без визитов", "emoji": "🆕", "description": "Есть в базе, без визитов"},
]

FILTER_FIELDS = {
    "phone": {"type": "phone_list", "column": "g.phone", "label": "Номер телефона"},
    "gender": {"type": "enum", "column": "up.gender", "label": "Пол", "options": [{"value": 1, "label": "Мужской"}, {"value": 2, "label": "Женский"}]},
    "age": {"type": "number", "column": "up.age", "label": "Возраст"},
    "registration_date": {"type": "date", "column": "up.registration_date", "label": "Дата регистрации"},
    "first_visit_date": {"type": "date", "column": "up.first_visit_date", "label": "Дата первого визита"},
    "last_visit_date": {"type": "date", "column": "up.last_visit_date", "label": "Дата последнего визита"},
    "visits_7d": {"type": "number", "column": "up.visits_7d", "label": "Визиты за 7 дней"},
    "visits_30d": {"type": "number", "column": "up.visits_30d", "label": "Визиты за 30 дней"},
    "visits_90d": {"type": "number", "column": "up.visits_90d", "label": "Визиты за 90 дней"},
    "total_visits": {"type": "number", "column": "up.total_visits", "label": "Всего визитов"},
    "avg_visits_per_month": {"type": "number", "column": "up.avg_visits_per_month", "label": "Среднее визитов в месяц"},
    "avg_session_minutes": {"type": "number", "column": "up.avg_session_minutes", "label": "Средняя длина сессии"},
    "max_session_minutes": {"type": "number", "column": "up.max_session_minutes", "label": "Макс. длина сессии"},
    "total_hours_30d": {"type": "number", "column": "up.total_hours_30d", "label": "Часов за 30 дней"},
    "total_hours_all": {"type": "number", "column": "up.total_hours_all", "label": "Часов за всё время"},
    "days_since_last_visit": {"type": "number", "column": "up.days_since_last_visit", "label": "Дней с последнего визита"},
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
    "avg_check_all": {"type": "number", "column": "up.avg_check_all", "label": "Средний чек за всё время"},
    "avg_check_30d": {"type": "number", "column": "up.avg_check_30d", "label": "Средний чек за 30 дней"},
    "last_payment_date": {"type": "date", "column": "up.last_payment_date", "label": "Последнее пополнение"},
    "missions_completed_count": {"type": "number", "column": "up.missions_completed_count", "label": "Выполнено миссий"},
    "missions_in_progress_count": {"type": "number", "column": "up.missions_in_progress_count", "label": "Миссий в процессе"},
    "last_mission_activity_date": {"type": "date", "column": "up.last_mission_activity_date", "label": "Последняя активность по миссиям"},
    "spins_count": {"type": "number", "column": "up.spins_count", "label": "Количество прокрутов"},
    "last_spin_date": {"type": "date", "column": "up.last_spin_date", "label": "Последний прокрут"},
    "lifetime_days": {"type": "number", "column": "up.lifetime_days", "label": "Дней с первого визита"},
    "avg_days_between_visits": {"type": "number", "column": "up.avg_days_between_visits", "label": "Средний интервал между визитами"},
    "is_active_30d": {"type": "bool", "column": "up.is_active_30d", "label": "Активен за 30 дней"},
    "is_active_90d": {"type": "bool", "column": "up.is_active_90d", "label": "Активен за 90 дней"},
    "has_telegram": {"type": "bool", "column": "up.has_telegram", "label": "Есть Telegram"},
    "crm_type": {
        "type": "enum",
        "column": "up.crm_type",
        "label": "CRM-группа",
        "options": [
            {"value": "top", "label": "TOP / Топ-гости"},
            {"value": "base", "label": "BASE / База"},
            {"value": "rare", "label": "RARE / Редкие"},
            {"value": "risk", "label": "RISK / В зоне риска"},
            {"value": "lost", "label": "LOST / Потерянные"},
            {"value": "dead", "label": "DEAD / Мёртвая база"},
            {"value": "no_visits", "label": "NO VISITS / Без визитов"},
        ],
    },
}

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
            "Мы начислили тебе 200 бонусов — приходи играть, будем ждать!"
        ),
        "days_inactive": 14,
        "bonus_amount": 200,
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
        "repeat_after_days": 3650,
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

def ensure_auto_mailings(conn, club_id: int) -> None:
    """
    Создаёт дефолтные авторассылки для клуба, если их ещё нет.
    Работает лениво: вызвал при открытии страницы — настройки появились.
    """
    with conn.cursor() as cur:
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
                    repeat_after_days,
                    is_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    description = VALUES(description),
                    updated_at = NOW()
                """,
                (
                    club_id,
                    code,
                    defaults["title"],
                    defaults["description"],
                    defaults["message_text"],
                    defaults["days_inactive"],
                    defaults["bonus_amount"],
                    defaults["repeat_after_days"],
                ),
            )

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
          AND up.has_telegram = 1
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
        result.append({
            **item,
            "count": counts.get(item["key"], 0),
            "rules": {
                "rules": [
                    {"field": "crm_type", "op": "=", "value": item["key"]}
                ]
            },
        })
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


def build_where_clause(club_id: int, rules: List[Dict[str, Any]]) -> Tuple[str, List[Any]]:
    where_parts = [
        "up.club_id = %s",
        "up.has_telegram = 1",
        "g.telegram_id IS NOT NULL",
    ]
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
        SELECT COUNT(*) AS cnt
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        {where_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row["cnt"] or 0)


def get_recipient_rows(conn, club_id: int, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    where_sql, params = build_where_clause(club_id, rules)
    sql = f"""
        SELECT
            up.guest_id,
            g.telegram_id
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        {where_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


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
                    status
                )
                VALUES (%s, %s, %s, 'pending')
                """,
                [
                    (
                        mailing_id,
                        row["guest_id"],
                        row["telegram_id"],
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_mailing_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                code VARCHAR(80) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                message_text TEXT NOT NULL,
                days_inactive INT NOT NULL DEFAULT 14,
                bonus_amount INT NOT NULL DEFAULT 200,
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
            """
        )
        _ensure_auto_mailing_column(cur, "days_inactive", "INT NOT NULL DEFAULT 14")
        _ensure_auto_mailing_column(cur, "bonus_amount", "INT NOT NULL DEFAULT 200")
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
                    repeat_after_days,
                    is_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    description = VALUES(description),
                    updated_at = NOW()
                """,
                (
                    club_id,
                    code,
                    defaults["title"],
                    defaults["description"],
                    defaults["message_text"],
                    defaults["days_inactive"],
                    defaults["bonus_amount"],
                    defaults["repeat_after_days"],
                ),
            )


def _build_inactive_auto_message(bonus_amount: int) -> str:
    bonus_amount = int(bonus_amount or 0)
    return (
        "Привет! Тебя давно не было в клубе 😔\n\n"
        f"Мы начислили тебе {bonus_amount} бонусов — приходи играть, будем ждать!"
    )


def _build_first_visit_survey_message(bonus_amount: int) -> str:
    bonus_amount = int(bonus_amount or 0)
    return (
        "Спасибо за визит! 🙌\n\n"
        f"Начислим еще {bonus_amount} бонусов для твоего второго визита если ответишь на 2 простых вопроса! "
        "Это займет всего 20с и очень поможет нам стать лучше 😁"
    )


def _build_auto_mailing_message(code: str, bonus_amount: int) -> str:
    if code == "first_visit_survey":
        return _build_first_visit_survey_message(bonus_amount)
    return _build_inactive_auto_message(bonus_amount)


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

    if bonus_amount is not None:
        bonus_amount = max(int(bonus_amount or 0), 1)
        fields.append("bonus_amount = %s")
        params.append(bonus_amount)
        fields.append("message_text = %s")
        params.append(_build_auto_mailing_message(code, bonus_amount))

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
            g.telegram_id
        FROM user_portrait up
        JOIN guests g ON g.club_id = up.club_id AND g.guest_id = up.guest_id
        WHERE up.club_id = %s
          AND up.has_telegram = 1
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
                    status
                )
                VALUES (%s, %s, %s, 'pending')
                """,
                [
                    (
                        mailing_id,
                        row["guest_id"],
                        row["telegram_id"],
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

    Раздача — это массовое начисление CM-бонусов выбранной аудитории + Telegram-уведомление.
    """
    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bonus_giveaways (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                filters_json JSON NULL,
                bonus_amount INT NOT NULL,
                message_text TEXT NOT NULL,
                mailing_id INT NULL,
                status VARCHAR(40) NOT NULL DEFAULT 'created',
                recipients_count INT NOT NULL DEFAULT 0,
                awarded_count INT NOT NULL DEFAULT 0,
                skipped_count INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME NULL,
                KEY idx_bonus_giveaways_club_created (club_id, created_at),
                KEY idx_bonus_giveaways_mailing (mailing_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bonus_giveaway_recipients (
                id INT AUTO_INCREMENT PRIMARY KEY,
                giveaway_id INT NOT NULL,
                club_id INT NOT NULL,
                guest_id INT NOT NULL,
                telegram_id BIGINT NULL,
                bonus_amount INT NOT NULL,
                transaction_status VARCHAR(40) NOT NULL DEFAULT 'pending',
                transaction_id INT NULL,
                mailing_recipient_id INT NULL,
                error_text TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                awarded_at DATETIME NULL,
                UNIQUE KEY uq_bonus_giveaway_guest (giveaway_id, guest_id),
                KEY idx_bonus_giveaway_recipients_guest (club_id, guest_id),
                KEY idx_bonus_giveaway_recipients_status (transaction_status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


def list_bonus_giveaways(conn, club_id: int) -> List[Dict[str, Any]]:
    ensure_bonus_giveaway_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                bonus_amount,
                status,
                recipients_count,
                awarded_count,
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
    parse_mode: str = "HTML",
) -> Dict[str, Any]:
    """Начисляет CM-бонусы выбранной аудитории и создаёт Telegram-рассылку.

    Фильтры используются ровно те же, что и в сегментах/ручной рассылке.
    Возвращает id раздачи, id рассылки и количество получателей.
    """
    bonus_amount = int(bonus_amount or 0)
    if bonus_amount <= 0:
        raise ValueError("Количество бонусов должно быть больше 0")

    message_text = (message_text or "").strip()
    if not message_text:
        raise ValueError("Сообщение раздачи пустое")

    ensure_bonus_giveaway_tables(conn)
    recipients = get_recipient_rows(conn, club_id, rules)
    recipients_count = len(recipients)
    filters_json = {"rules": rules, "type": "bonus_giveaway", "bonus_amount": bonus_amount}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bonus_giveaways (
                club_id,
                filters_json,
                bonus_amount,
                message_text,
                status,
                recipients_count
            )
            VALUES (%s, %s, %s, %s, 'processing', %s)
            """,
            (
                club_id,
                json.dumps(filters_json, ensure_ascii=False),
                bonus_amount,
                message_text,
                recipients_count,
            ),
        )
        giveaway_id = cur.lastrowid

        awarded_count = 0
        skipped_count = 0
        for row in recipients:
            guest_id = int(row["guest_id"])
            telegram_id = row.get("telegram_id")
            error_text = None
            status = "awarded"
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
                )
                if awarded:
                    awarded_count += 1
                else:
                    status = "skipped"
                    skipped_count += 1
                    error_text = "Дубликат операции"
            except Exception as exc:
                status = "failed"
                skipped_count += 1
                error_text = str(exc)[:1000]

            cur.execute(
                """
                INSERT INTO bonus_giveaway_recipients (
                    giveaway_id,
                    club_id,
                    guest_id,
                    telegram_id,
                    bonus_amount,
                    transaction_status,
                    error_text,
                    awarded_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, IF(%s = 'awarded', NOW(), NULL))
                """,
                (
                    giveaway_id,
                    club_id,
                    guest_id,
                    telegram_id,
                    bonus_amount,
                    status,
                    error_text,
                    status,
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
                skipped_count = %s,
                finished_at = NOW()
            WHERE id = %s AND club_id = %s
            """,
            (mailing_id, awarded_count, skipped_count, giveaway_id, club_id),
        )

    return {
        "giveaway_id": giveaway_id,
        "mailing_id": mailing_id,
        "recipients_count": recipients_count,
        "awarded_count": awarded_count,
        "skipped_count": skipped_count,
        "bonus_amount": bonus_amount,
    }
