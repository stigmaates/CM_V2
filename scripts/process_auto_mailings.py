import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv

load_dotenv()

from app.config import AUTO_MAILING_TIMEZONE
from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.first_visit_survey import (
    create_first_visit_survey,
    get_first_visit_survey_candidates,
    send_first_visit_survey_invite,
)
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run
from app.services.mailing import (
    create_mailing_for_recipients,
    get_inactive_auto_mailing_recipients,
)
from app.services.wheel import _calculate_streak_rows
from scripts.process_mailings import process_one_mailing
from scripts.sync_utils import table_has_column


def process_inactive_14_bonus(conn, setting: dict) -> int:
    club_id = setting["club_id"]
    code = setting["code"]
    days_inactive = int(setting.get("days_inactive") or 14)
    bonus_amount = int(setting.get("bonus_amount") or 200)
    bonus_expires_at = datetime.utcnow() + timedelta(days=7)
    repeat_after_days = int(setting.get("repeat_after_days") or 30)
    message_text = setting.get("message_text") or (
        "Привет! Тебя давно не было в клубе 😔\n\n"
        f"Мы начислили тебе {bonus_amount} бонусов на 7 дней — приходи играть, будем ждать!"
    )

    recipients = get_inactive_auto_mailing_recipients(
        conn=conn,
        club_id=club_id,
        automation_code=code,
        days_inactive=days_inactive,
        repeat_after_days=repeat_after_days,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auto_mailing_settings
            SET last_run_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (setting["id"],),
        )
    conn.commit()

    if not recipients:
        return 0

    mailing = create_mailing_for_recipients(
        conn=conn,
        club_id=club_id,
        recipients=recipients,
        message_text=message_text,
        parse_mode="HTML",
        filters_json={
            "auto_mailing": code,
            "days_inactive": days_inactive,
            "bonus_amount": bonus_amount,
            "is_expiring": True,
            "expires_after_seconds": 7 * 24 * 60 * 60,
            "repeat_after_days": repeat_after_days,
        },
    )

    mailing_id = mailing["mailing_id"]

    with conn.cursor() as cur:
        ensure_cm_bonus_tables(cur)
        for row in recipients:
            add_cm_bonus_transaction(
                cursor=cur,
                guest_id=int(row["guest_id"]),
                club_id=int(club_id),
                amount=bonus_amount,
                source_type="auto_mailing",
                source_id=str(mailing_id),
                description=f"Авторассылка: {setting.get('title') or code} (сгорает через 7 дней)",
                status="done",
                expires_at=bonus_expires_at,
            )

    conn.commit()

    process_one_mailing(conn, mailing_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auto_mailing_logs (
                club_id,
                automation_code,
                guest_id,
                telegram_id,
                mailing_id,
                mailing_recipient_id,
                status,
                error_text,
                sent_at
            )
            SELECT
                %s,
                %s,
                mr.guest_id,
                mr.telegram_id,
                mr.mailing_id,
                mr.id,
                mr.status,
                mr.error_text,
                mr.sent_at
            FROM mailing_recipients mr
            WHERE mr.mailing_id = %s
            """,
            (club_id, code, mailing_id),
        )
        cur.execute(
            """
            UPDATE auto_mailing_settings
            SET last_mailing_id = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (mailing_id, setting["id"]),
        )
    conn.commit()
    return int(mailing.get("recipients_count") or 0)


def process_first_visit_survey(conn, setting: dict) -> int:
    bonus_amount = int(setting.get("bonus_amount") or 100)
    message_text = setting.get("message_text") or (
        "Спасибо за первый визит! 🙌\n\n"
        f"Пожалуйста, потрать 30 секунд на быстрый опрос — за прохождение начислим {bonus_amount} бонусов рубль к рублю."
    )

    candidates = get_first_visit_survey_candidates(
        conn=conn,
        setting=setting,
        delay_minutes=20,
        window_hours=24,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auto_mailing_settings
            SET last_run_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (setting["id"],),
        )
    conn.commit()

    sent_count = 0
    for candidate in candidates:
        survey_id = create_first_visit_survey(conn, setting, candidate)
        conn.commit()
        if not survey_id:
            continue
        try:
            if send_first_visit_survey_invite(conn, survey_id, message_text):
                sent_count += 1
        except Exception as exc:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE first_visit_surveys
                    SET status = 'invite_failed', feedback_text = %s
                    WHERE id = %s
                    """,
                    (str(exc)[:1000], survey_id),
                )
            conn.commit()

    return sent_count


def _ensure_auto_mailing_logs_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auto_mailing_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                club_id INT NOT NULL,
                automation_code VARCHAR(80) NOT NULL,
                guest_id BIGINT NOT NULL,
                telegram_id BIGINT NULL,
                mailing_id INT NULL,
                mailing_recipient_id INT NULL,
                status VARCHAR(40) NULL,
                error_text TEXT NULL,
                sent_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_auto_mailing_logs_guest_code (club_id, automation_code, guest_id, created_at),
                KEY idx_auto_mailing_logs_mailing (mailing_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)


def _get_auto_mailing_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(AUTO_MAILING_TIMEZONE or "Europe/Moscow"))
    except Exception:
        return datetime.now()


def _is_streak_reminder_send_window() -> bool:
    now = _get_auto_mailing_now()
    return 9 <= now.hour < 21


def _format_streak_reminder_message(
    template: str, club_name: str, streak_days: int, cycle_end, next_reward: int
) -> str:
    text = template or (
        "Привет! У тебя в {club_name} стрик из дней — {streak_days}. "
        "Приди еще раз до {date} и получи {next_reward} жетонов для колеса фортуны!"
    )
    date_text = cycle_end.strftime("%d.%m") if hasattr(cycle_end, "strftime") else str(cycle_end)
    return (
        text.replace("[club_name]", str(club_name or "клубе"))
        .replace("[х]", str(streak_days))
        .replace("[x]", str(streak_days))
        .replace("[date]", date_text)
        .replace("[y]", str(next_reward))
        .replace("{club_name}", str(club_name or "клубе"))
        .replace("{streak_days}", str(streak_days))
        .replace("{x}", str(streak_days))
        .replace("{date}", date_text)
        .replace("{next_reward}", str(next_reward))
        .replace("{y}", str(next_reward))
    )


def _get_streak_expiring_candidates(conn, setting: dict) -> list[dict]:
    club_id = int(setting["club_id"])
    with conn.cursor() as cur:
        _ensure_auto_mailing_logs_table(conn)
        cur.execute(
            """
            SELECT name
            FROM clubs
            WHERE club_id = %s
            LIMIT 1
            """,
            (club_id,),
        )
        club_row = cur.fetchone() or {}
        club_name = club_row.get("name") or "клубе"

        cur.execute(
            """
            SELECT tokens_start_date, is_enabled
            FROM club_wheel_settings
            WHERE club_id = %s
            LIMIT 1
            """,
            (club_id,),
        )
        wheel_settings = cur.fetchone() or {}
        if (
            not wheel_settings
            or not int(wheel_settings.get("is_enabled") or 0)
            or not wheel_settings.get("tokens_start_date")
        ):
            return []

        tokens_start_date = wheel_settings["tokens_start_date"]
        cur.execute(
            """
            SELECT
                g.guest_id,
                g.telegram_id,
                DATE(gs.date_start) AS visit_day
            FROM guests g
            JOIN guest_sessions gs
              ON gs.club_id = g.club_id
             AND gs.guest_id = g.guest_id
            WHERE g.club_id = %s
              AND g.telegram_id IS NOT NULL
              AND TRIM(CAST(g.telegram_id AS CHAR)) <> ''
              AND gs.date_start IS NOT NULL
              AND gs.date_start >= %s
            GROUP BY g.guest_id, g.telegram_id, DATE(gs.date_start)
            ORDER BY g.guest_id, DATE(gs.date_start)
            """,
            (club_id, tokens_start_date),
        )
        rows = cur.fetchall() or []

    today = _get_auto_mailing_now().date()
    visits_by_guest = {}
    telegram_by_guest = {}
    for row in rows:
        guest_id = int(row["guest_id"])
        telegram_by_guest[guest_id] = row.get("telegram_id")
        visit_day = row.get("visit_day")
        if hasattr(visit_day, "date"):
            visit_day = visit_day.date()
        visits_by_guest.setdefault(guest_id, []).append(visit_day)

    candidates = []
    with conn.cursor() as cur:
        for guest_id, visit_days in visits_by_guest.items():
            visit_days = [day for day in visit_days if day]
            streak_rows = _calculate_streak_rows(visit_days)
            if not streak_rows:
                continue
            last = streak_rows[-1]
            cycle_start = last["cycle_start"]
            cycle_end = last["cycle_end"]
            if today >= cycle_end:
                continue

            current_cycle_rows = [row for row in streak_rows if row["cycle_index"] == last["cycle_index"]]
            streak_days = len(current_cycle_rows)
            if streak_days < 2:
                continue

            days_left = (cycle_end - today).days
            if days_left < 1 or days_left > 3:
                continue

            cur.execute(
                """
                SELECT id
                FROM auto_mailing_logs
                WHERE club_id = %s
                  AND automation_code = %s
                  AND guest_id = %s
                  AND created_at >= %s
                  AND created_at < %s
                LIMIT 1
                """,
                (club_id, setting["code"], guest_id, cycle_start, cycle_end),
            )
            if cur.fetchone():
                continue

            candidates.append(
                {
                    "guest_id": guest_id,
                    "telegram_id": telegram_by_guest.get(guest_id),
                    "club_id": club_id,
                    "club_name": club_name,
                    "streak_days": streak_days,
                    "cycle_start": cycle_start,
                    "cycle_end": cycle_end,
                    "days_left": days_left,
                    "next_reward": min(streak_days + 1, 7),
                }
            )
    return candidates


def process_streak_expiring_reminder(conn, setting: dict) -> int:
    club_id = int(setting["club_id"])
    code = setting["code"]

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auto_mailing_settings
            SET last_run_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (setting["id"],),
        )
    conn.commit()

    if not _is_streak_reminder_send_window():
        return 0

    candidates = _get_streak_expiring_candidates(conn, setting)
    if not candidates:
        return 0

    sent_count = 0
    template = setting.get("message_text") or ""
    for candidate in candidates:
        message_text = _format_streak_reminder_message(
            template=template,
            club_name=candidate.get("club_name"),
            streak_days=int(candidate.get("streak_days") or 0),
            cycle_end=candidate.get("cycle_end"),
            next_reward=int(candidate.get("next_reward") or 0),
        )
        mailing = create_mailing_for_recipients(
            conn=conn,
            club_id=club_id,
            recipients=[candidate],
            message_text=message_text,
            parse_mode="HTML",
            filters_json={
                "auto_mailing": code,
                "streak_days": candidate.get("streak_days"),
                "cycle_end": str(candidate.get("cycle_end")),
                "next_reward": candidate.get("next_reward"),
                "send_window": "09:00-21:00",
            },
        )
        mailing_id = mailing["mailing_id"]
        conn.commit()
        process_one_mailing(conn, mailing_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_mailing_logs (
                    club_id,
                    automation_code,
                    guest_id,
                    telegram_id,
                    mailing_id,
                    mailing_recipient_id,
                    status,
                    error_text,
                    sent_at
                )
                SELECT
                    %s,
                    %s,
                    mr.guest_id,
                    mr.telegram_id,
                    mr.mailing_id,
                    mr.id,
                    mr.status,
                    mr.error_text,
                    mr.sent_at
                FROM mailing_recipients mr
                WHERE mr.mailing_id = %s
                """,
                (club_id, code, mailing_id),
            )
            cur.execute(
                """
                UPDATE auto_mailing_settings
                SET last_mailing_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (mailing_id, setting["id"]),
            )
        conn.commit()
        sent_count += int(mailing.get("recipients_count") or 0)
    return sent_count


def process_auto_mailings() -> dict:
    conn = get_db_connection()
    total_created = 0
    processed = []
    try:
        with conn.cursor() as cur:
            if table_has_column(cur, "clubs", "service_enabled"):
                cur.execute("""
                    SELECT ams.*
                    FROM auto_mailing_settings ams
                    JOIN clubs c ON c.club_id = ams.club_id
                    WHERE ams.is_enabled = 1
                      AND COALESCE(c.service_enabled, 1) = 1
                    ORDER BY ams.club_id, ams.id
                    """)
            else:
                cur.execute("""
                    SELECT *
                    FROM auto_mailing_settings
                    WHERE is_enabled = 1
                    ORDER BY club_id, id
                    """)
            settings = cur.fetchall()

        for setting in settings:
            code = setting.get("code")
            club_id = int(setting["club_id"])
            lock = job_lock("process_auto_mailing", club_id=club_id, resource_id=code, ttl_minutes=60)
            acquired_lock = lock.__enter__()
            job_run_id = start_job_run(
                "process_auto_mailing",
                club_id=club_id,
                metadata={"code": code, "setting_id": setting.get("id")},
            )
            if not acquired_lock.acquired:
                finish_job_run(
                    job_run_id,
                    "skipped_locked",
                    metadata={"code": code, "reason": "auto mailing already running"},
                )
                lock.__exit__(None, None, None)
                continue
            try:
                if code == "inactive_14_bonus":
                    created = process_inactive_14_bonus(conn, setting)
                elif code == "first_visit_survey":
                    created = process_first_visit_survey(conn, setting)
                elif code == "streak_expiring_reminder":
                    created = process_streak_expiring_reminder(conn, setting)
                else:
                    finish_job_run(
                        job_run_id,
                        "success",
                        rows_received=0,
                        rows_saved=0,
                        metadata={"code": code, "skipped": "unknown_code"},
                    )
                    continue

                total_created += created
                processed.append({"club_id": club_id, "code": code, "recipients": created})
                finish_job_run(
                    job_run_id,
                    "success",
                    rows_received=created,
                    rows_saved=created,
                    metadata={"code": code, "setting_id": setting.get("id")},
                )
            except Exception as exc:
                finish_job_run(job_run_id, "error", error_text=str(exc), metadata={"code": code})
                raise
            finally:
                lock.__exit__(None, None, None)

        return {"processed": processed, "recipients_created": total_created}
    finally:
        conn.close()


def main():
    result = process_auto_mailings()
    print(result)


if __name__ == "__main__":
    main()
