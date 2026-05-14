import json
import re

from app.core import get_db_connection


def build_guest_mission_reward_display(reward_text, token_reward: int, cm_bonus_reward: int = 0) -> str:
    """Одна строка награды для гостя: текстовый приз + жетоны + CM-бонусы без дублей."""
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
        bonus_line = f"🎁 +{br} CM-бонусов"
        if not (("cm" in lowered or "см" in lowered or "бонус" in lowered) and re.search(rf"(?:^|\D){br}(?!\d)", rt)):
            parts.append(bonus_line)

    return " · ".join(parts)


_BONUS_QUANTITY_IN_REWARD_TEXT = re.compile(
    r"(?i)\d[\d\s.,]*\s*(бонус(?:ов|а|ы)?|bonus(?:es)?)\b"
    r"|\b(бонус(?:ов|а|ы)?|bonus(?:es)?)\s*[:\-–+]?\s*\d"
)


def reward_text_contains_bonus_quantity(reward_text: str | None) -> bool:
    """True, если в поле «Приз» указано количество бонусов — это дублирует CM-бонусы."""
    if not reward_text or not str(reward_text).strip():
        return False
    t = str(reward_text).lower().replace("ё", "е")
    return bool(_BONUS_QUANTITY_IN_REWARD_TEXT.search(t))


_mission_reward_columns_ready = False


def ensure_mission_reward_columns(cursor):
    """Make older databases compatible with mission rewards.

    reward_text is a human-readable prize label.
    token_reward is the automatic number of wheel tokens credited once per completed mission.
    cm_bonus_reward is the automatic number of ClubModule bonuses credited once per completed mission.
    """
    global _mission_reward_columns_ready
    if _mission_reward_columns_ready:
        return

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'reward_text'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE club_missions "
            "ADD COLUMN reward_text VARCHAR(255) NULL AFTER target_amount"
        )

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'token_reward'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE club_missions "
            "ADD COLUMN token_reward INT NOT NULL DEFAULT 0 AFTER reward_text"
        )

    cursor.execute("SHOW COLUMNS FROM club_missions LIKE 'cm_bonus_reward'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE club_missions "
            "ADD COLUMN cm_bonus_reward INT NOT NULL DEFAULT 0 AFTER token_reward"
        )

    _mission_reward_columns_ready = True


def ensure_mission_reward_text_column(cursor):
    ensure_mission_reward_columns(cursor)



def get_mission_templates():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, code, name, short_description, target_metric, config_schema
                FROM mission_templates
                WHERE is_active = 1
                ORDER BY id
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                if row.get("config_schema") and isinstance(row["config_schema"], str):
                    try:
                        row["config_schema"] = json.loads(row["config_schema"])
                    except Exception:
                        row["config_schema"] = None
            return rows
    finally:
        conn.close()


def get_mission_template_by_id(template_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
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
            if row and row.get("config_schema") and isinstance(row["config_schema"], str):
                try:
                    row["config_schema"] = json.loads(row["config_schema"])
                except Exception:
                    row["config_schema"] = None
            return row
    finally:
        conn.close()


def _decode_mission_rows(rows):
    for row in rows:
        if row.get("config") and isinstance(row["config"], str):
            try:
                row["config"] = json.loads(row["config"])
            except Exception:
                row["config"] = None
        if row.get("config_schema") and isinstance(row["config_schema"], str):
            try:
                row["config_schema"] = json.loads(row["config_schema"])
            except Exception:
                row["config_schema"] = None
    return rows


def get_club_missions(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            cursor.execute(
                """
                SELECT cm.id,
                       cm.club_id,
                       cm.mission_template_id,
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
            cursor.execute(
                """
                SELECT cm.id,
                       cm.club_id,
                       cm.mission_template_id,
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


def build_period_filter(mission):
    start_at = mission.get("start_at")
    end_at = mission.get("end_at")
    conditions = []
    params = []

    if start_at:
        conditions.append("date_start >= %s")
        params.append(start_at)
    if end_at:
        conditions.append("date_start <= %s")
        params.append(end_at)

    return conditions, params


def build_mission_config_from_form(template, form):
    config = {}
    code = template["code"]

    if code == "long_visits_count":
        min_hours = form.get("min_hours", "").strip()
        if not min_hours:
            raise ValueError("Укажи минимальное количество часов")
        try:
            min_hours = int(min_hours)
        except ValueError:
            raise ValueError("min_hours должен быть числом")
        if min_hours <= 0:
            raise ValueError("min_hours должен быть больше 0")
        config["min_hours"] = min_hours

    return config or None


def create_club_mission(club_id: int, mission_template_id: int, target_amount: int, start_at=None, end_at=None, config=None, reward_text=None, token_reward: int = 0, cm_bonus_reward: int = 0):
    if start_at and end_at and end_at < start_at:
        raise ValueError("Дата окончания не может быть раньше даты начала")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            cursor.execute(
                """
                SELECT id
                FROM club_missions
                WHERE club_id = %s
                  AND mission_template_id = %s
                LIMIT 1
                """,
                (club_id, mission_template_id),
            )
            if cursor.fetchone():
                raise ValueError("Это задание уже добавлено в клуб")

            cursor.execute(
                """
                INSERT INTO club_missions (
                    club_id,
                    mission_template_id,
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
                VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, 0)
                """,
                (
                    club_id,
                    mission_template_id,
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
    finally:
        conn.close()


def update_club_mission(mission_id: int, club_id: int, target_amount: int, start_at=None, end_at=None, config=None, is_enabled=1, reward_text=None, token_reward: int = 0, cm_bonus_reward: int = 0):
    if start_at and end_at and end_at < start_at:
        raise ValueError("Дата окончания не может быть раньше даты начала")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_mission_reward_columns(cursor)
            cursor.execute(
                """
                UPDATE club_missions
                SET target_amount = %s,
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


def calculate_mission_progress(guest_id: int, club_id: int, mission):
    metric = mission["target_metric"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            period_conditions, period_params = build_period_filter(mission)

            if metric == "visits_count":
                where_parts = ["guest_id = %s", "club_id = %s"] + period_conditions
                params = [guest_id, club_id] + period_params
                sql = f"SELECT COUNT(*) AS cnt FROM guest_sessions WHERE {' AND '.join(where_parts)}"
                cursor.execute(sql, params)
                return cursor.fetchone()["cnt"] or 0

            if metric == "night_visits_count":
                where_parts = [
                    "guest_id = %s",
                    "club_id = %s",
                    "(HOUR(date_start) >= 22 OR HOUR(date_start) < 8)",
                ] + period_conditions
                params = [guest_id, club_id] + period_params
                sql = f"SELECT COUNT(*) AS cnt FROM guest_sessions WHERE {' AND '.join(where_parts)}"
                cursor.execute(sql, params)
                return cursor.fetchone()["cnt"] or 0

            if metric == "weekend_visits_count":
                where_parts = [
                    "guest_id = %s",
                    "club_id = %s",
                    "DAYOFWEEK(date_start) IN (1, 7)",
                ] + period_conditions
                params = [guest_id, club_id] + period_params
                sql = f"SELECT COUNT(*) AS cnt FROM guest_sessions WHERE {' AND '.join(where_parts)}"
                cursor.execute(sql, params)
                return cursor.fetchone()["cnt"] or 0

            if metric == "long_visits_count":
                min_hours = 0
                config = mission.get("config") or {}
                if isinstance(config, dict):
                    min_hours = int(config.get("min_hours", 0) or 0)

                where_parts = [
                    "guest_id = %s",
                    "club_id = %s",
                    "TIMESTAMPDIFF(HOUR, date_start, date_stop) >= %s",
                ] + period_conditions
                params = [guest_id, club_id, min_hours] + period_params
                sql = f"SELECT COUNT(*) AS cnt FROM guest_sessions WHERE {' AND '.join(where_parts)}"
                cursor.execute(sql, params)
                return cursor.fetchone()["cnt"] or 0

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
                "name": mission["name"],
                "description": mission["short_description"],
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
