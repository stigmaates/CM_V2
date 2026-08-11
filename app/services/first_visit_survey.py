from __future__ import annotations

from html import escape
from typing import Any, Dict, List

import httpx

from app.config import BOT_TOKEN, TG_PROXY_URL
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.wheel import ensure_token_tables

_first_visit_tables_ready = False
_club_social_columns_ready = False


SOCIAL_COLUMNS = {
    "instagram_url": "VARCHAR(255) NULL",
    "youtube_url": "VARCHAR(255) NULL",
    "vk_url": "VARCHAR(255) NULL",
    "telegram_channel_url": "VARCHAR(255) NULL",
    "yandex_maps_url": "VARCHAR(255) NULL",
    "two_gis_url": "VARCHAR(255) NULL",
}


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
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


def ensure_club_social_columns(cursor) -> None:
    global _club_social_columns_ready
    if _club_social_columns_ready:
        return
    for column_name, ddl in SOCIAL_COLUMNS.items():
        _ensure_column(cursor, "clubs", column_name, ddl)
    _club_social_columns_ready = True


def ensure_first_visit_survey_tables(cursor) -> None:
    global _first_visit_tables_ready
    ensure_cm_bonus_tables(cursor)
    ensure_token_tables(cursor)
    ensure_club_social_columns(cursor)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS first_visit_surveys (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            telegram_id BIGINT NOT NULL,
            auto_mailing_setting_id INT NULL,
            session_id BIGINT NULL,
            session_ended_at DATETIME NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'invited',
            rating INT NULL,
            feedback_text TEXT NULL,
            bonus_amount INT NOT NULL DEFAULT 100,
            bonus_awarded TINYINT(1) NOT NULL DEFAULT 0,
            invite_message_id BIGINT NULL,
            invite_sent_at DATETIME NULL,
            started_at DATETIME NULL,
            completed_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_first_visit_survey_guest (club_id, guest_id),
            KEY idx_first_visit_survey_status (status),
            KEY idx_first_visit_survey_telegram (telegram_id),
            KEY idx_first_visit_survey_session (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    # older installs may have table but not newer columns
    _ensure_column(cursor, "first_visit_surveys", "auto_mailing_setting_id", "INT NULL")
    _ensure_column(cursor, "first_visit_surveys", "invite_message_id", "BIGINT NULL")
    _first_visit_tables_ready = True


def get_club_social_links(conn, club_id: int) -> Dict[str, str]:
    with conn.cursor() as cur:
        ensure_club_social_columns(cur)
        cur.execute(
            """
            SELECT instagram_url, youtube_url, vk_url, telegram_channel_url, yandex_maps_url, two_gis_url
            FROM clubs
            WHERE club_id = %s
            LIMIT 1
            """,
            (club_id,),
        )
        row = cur.fetchone() or {}
    return {
        "instagram_url": (row.get("instagram_url") or "").strip(),
        "youtube_url": (row.get("youtube_url") or "").strip(),
        "vk_url": (row.get("vk_url") or "").strip(),
        "telegram_channel_url": (row.get("telegram_channel_url") or "").strip(),
        "yandex_maps_url": (row.get("yandex_maps_url") or "").strip(),
        "two_gis_url": (row.get("two_gis_url") or "").strip(),
    }


def build_social_links_message(conn, club_id: int, rating: int | None = None) -> str:
    links = get_club_social_links(conn, club_id)
    rows = []

    if links.get("instagram_url"):
        rows.append(
            f'📸 <a href="{escape(links["instagram_url"], quote=True)}">Instagram* (*запрещена на территории РФ)</a>'
        )

    if links.get("youtube_url"):
        rows.append(f'▶️ <a href="{escape(links["youtube_url"], quote=True)}">YouTube</a>')

    if links.get("vk_url"):
        rows.append(f'💬 <a href="{escape(links["vk_url"], quote=True)}">VK</a>')

    if links.get("telegram_channel_url"):
        rows.append(f'📢 <a href="{escape(links["telegram_channel_url"], quote=True)}">Telegram-канал</a>')

    if links.get("yandex_maps_url"):
        rows.append(f'⭐ <a href="{escape(links["yandex_maps_url"], quote=True)}">Оставить отзыв на Яндекс Картах</a>')

    if links.get("two_gis_url"):
        rows.append(f'🗺 <a href="{escape(links["two_gis_url"], quote=True)}">Оставить отзыв в 2ГИС</a>')

    message_parts = ["Спасибо за ответ! Бонусы уже начислены ✅"]

    review_links_available = bool(links.get("yandex_maps_url") or links.get("two_gis_url"))
    if int(rating or 0) >= 4 and review_links_available:
        message_parts.append(
            "Если тебе всё понравилось, оставь, пожалуйста, отзыв на картах — "
            "за отзыв можно получить дополнительные бонусы по акции ⭐"
        )

    if rows:
        message_parts.append(
            "Следи за нами в соцсетях, чтобы не пропускать турниры, акции и новости клуба:\n\n" + "\n".join(rows)
        )

    return "\n\n".join(message_parts)


def get_first_visit_survey_candidates(
    conn, setting: dict, delay_minutes: int = 20, window_hours: int = 24
) -> List[Dict[str, Any]]:
    club_id = int(setting["club_id"])
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            """
            SELECT
                gs.id AS session_id,
                gs.club_id,
                gs.guest_id,
                gs.date_stop AS session_ended_at,
                g.telegram_id,
                g.fio,
                c.name AS club_name,
                COALESCE(cbb.balance, 0) AS cm_bonus_balance,
                COALESCE(gwtb.balance, 0) AS token_balance,
                (
                    SELECT COUNT(*)
                    FROM guest_sessions gs7
                    WHERE gs7.club_id = gs.club_id
                      AND gs7.guest_id = gs.guest_id
                      AND gs7.date_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ) AS sessions_7d,
                (
                    SELECT COUNT(*)
                    FROM guest_sessions gs30
                    WHERE gs30.club_id = gs.club_id
                      AND gs30.guest_id = gs.guest_id
                      AND gs30.date_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                ) AS sessions_30d,
                (
                    SELECT COUNT(*)
                    FROM guest_sessions gs90
                    WHERE gs90.club_id = gs.club_id
                      AND gs90.guest_id = gs.guest_id
                      AND gs90.date_start >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                ) AS sessions_90d,
                (
                    SELECT COUNT(*)
                    FROM guest_case_openings gco
                    WHERE gco.club_id = gs.club_id
                      AND gco.guest_id = gs.guest_id
                ) AS case_openings_count,
                COUNT(gs_all.id) AS sessions_count
            FROM guest_sessions gs
            JOIN guests g
              ON g.club_id = gs.club_id
             AND g.guest_id = gs.guest_id
            JOIN clubs c
              ON c.club_id = gs.club_id
            JOIN guest_sessions gs_all
              ON gs_all.club_id = gs.club_id
             AND gs_all.guest_id = gs.guest_id
             AND gs_all.date_stop IS NOT NULL
            LEFT JOIN cm_bonus_balances cbb
              ON cbb.club_id = gs.club_id
             AND cbb.guest_id = gs.guest_id
            LEFT JOIN guest_wheel_token_balances gwtb
              ON gwtb.club_id = gs.club_id
             AND gwtb.guest_id = gs.guest_id
            LEFT JOIN first_visit_surveys fvs
              ON fvs.club_id = gs.club_id
             AND fvs.guest_id = gs.guest_id
            WHERE gs.club_id = %s
              AND gs.date_stop IS NOT NULL
              AND g.telegram_id IS NOT NULL
              AND gs.date_stop <= DATE_SUB(NOW(), INTERVAL %s MINUTE)
              AND gs.date_stop >= DATE_SUB(NOW(), INTERVAL %s HOUR)
              AND fvs.id IS NULL
            GROUP BY
                gs.id,
                gs.club_id,
                gs.guest_id,
                gs.date_stop,
                g.telegram_id,
                g.fio,
                c.name,
                cbb.balance,
                gwtb.balance
            HAVING sessions_count = 1
            ORDER BY gs.date_stop ASC
            LIMIT 200
            """,
            (club_id, int(delay_minutes), int(window_hours)),
        )
        return cur.fetchall()


def create_first_visit_survey(conn, setting: dict, candidate: dict) -> int | None:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            """
            INSERT IGNORE INTO first_visit_surveys (
                club_id,
                guest_id,
                telegram_id,
                auto_mailing_setting_id,
                session_id,
                session_ended_at,
                bonus_amount,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'created', NOW())
            """,
            (
                int(candidate["club_id"]),
                int(candidate["guest_id"]),
                int(candidate["telegram_id"]),
                setting.get("id"),
                candidate.get("session_id"),
                candidate.get("session_ended_at"),
                int(setting.get("bonus_amount") or 100),
            ),
        )
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)


def _tg_request(method: str, payload: dict):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не настроен")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    client_kwargs = {"timeout": 60}
    if TG_PROXY_URL:
        client_kwargs["proxy"] = TG_PROXY_URL
    with httpx.Client(**client_kwargs) as client:
        return client.post(url, json=payload)


def send_first_visit_survey_invite(conn, survey_id: int, message_text: str) -> bool:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            "SELECT * FROM first_visit_surveys WHERE id = %s LIMIT 1",
            (survey_id,),
        )
        survey = cur.fetchone()
    if not survey:
        return False

    payload = {
        "chat_id": int(survey["telegram_id"]),
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [[{"text": "Пройти опрос", "callback_data": f"first_visit_survey_start:{survey_id}"}]]
        },
    }
    response = _tg_request("sendMessage", payload)
    ok = response.status_code == 200 and response.json().get("ok") is True
    with conn.cursor() as cur:
        if ok:
            message_id = response.json().get("result", {}).get("message_id")
            cur.execute(
                """
                UPDATE first_visit_surveys
                SET status = 'invited', invite_sent_at = NOW(), invite_message_id = %s
                WHERE id = %s
                """,
                (message_id, survey_id),
            )
        else:
            cur.execute(
                """
                UPDATE first_visit_surveys
                SET status = 'invite_failed', feedback_text = %s
                WHERE id = %s
                """,
                (response.text[:1000], survey_id),
            )
    conn.commit()
    return ok


def get_survey_for_callback(conn, survey_id: int, telegram_id: int | None = None) -> Dict[str, Any] | None:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        sql = "SELECT * FROM first_visit_surveys WHERE id = %s"
        params = [survey_id]
        if telegram_id is not None:
            sql += " AND telegram_id = %s"
            params.append(int(telegram_id))
        sql += " LIMIT 1"
        cur.execute(sql, tuple(params))
        return cur.fetchone()


def mark_survey_started(conn, survey_id: int) -> None:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            """
            UPDATE first_visit_surveys
            SET status = 'in_progress', started_at = COALESCE(started_at, NOW())
            WHERE id = %s AND status IN ('created', 'invited', 'in_progress')
            """,
            (survey_id,),
        )
    conn.commit()


def save_survey_rating(conn, survey_id: int, rating: int) -> None:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            """
            UPDATE first_visit_surveys
            SET rating = %s, status = 'awaiting_feedback', updated_at = NOW()
            WHERE id = %s AND status IN ('invited', 'in_progress', 'awaiting_feedback')
            """,
            (int(rating), survey_id),
        )
    conn.commit()


def find_waiting_survey(conn, telegram_id: int) -> Dict[str, Any] | None:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute(
            """
            SELECT *
            FROM first_visit_surveys
            WHERE telegram_id = %s
              AND status = 'awaiting_feedback'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (int(telegram_id),),
        )
        return cur.fetchone()


def complete_survey_and_award(conn, survey_id: int, feedback_text: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        ensure_first_visit_survey_tables(cur)
        cur.execute("SELECT * FROM first_visit_surveys WHERE id = %s FOR UPDATE", (survey_id,))
        survey = cur.fetchone()
        if not survey:
            conn.rollback()
            return {"ok": False, "message": "Опрос не найден"}

        if survey.get("status") == "completed":
            conn.commit()
            return {"ok": True, "already_done": True, "survey": survey}

        bonus_amount = int(survey.get("bonus_amount") or 0)
        awarded = False
        if bonus_amount > 0 and not int(survey.get("bonus_awarded") or 0):
            awarded = add_cm_bonus_transaction(
                cursor=cur,
                guest_id=int(survey["guest_id"]),
                club_id=int(survey["club_id"]),
                amount=bonus_amount,
                source_type="first_visit_survey",
                source_id=str(survey_id),
                description="Бонусы за опрос после первого визита",
                status="done",
            )

        cur.execute(
            """
            UPDATE first_visit_surveys
            SET status = 'completed',
                feedback_text = %s,
                bonus_awarded = 1,
                completed_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            ((feedback_text or "").strip()[:5000], survey_id),
        )
    conn.commit()
    survey["bonus_awarded"] = 1
    return {"ok": True, "survey": survey, "awarded": awarded}
