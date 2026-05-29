import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.mailing import (
    create_mailing_for_recipients,
    get_inactive_auto_mailing_recipients,
)
from app.services.first_visit_survey import (
    create_first_visit_survey,
    get_first_visit_survey_candidates,
    send_first_visit_survey_invite,
)
from scripts.process_mailings import process_one_mailing


def process_inactive_14_bonus(conn, setting: dict) -> int:
    club_id = setting["club_id"]
    code = setting["code"]
    days_inactive = int(setting.get("days_inactive") or 14)
    bonus_amount = int(setting.get("bonus_amount") or 200)
    repeat_after_days = int(setting.get("repeat_after_days") or 30)
    message_text = setting.get("message_text") or (
        "Привет! Тебя давно не было в клубе 😔\n\n"
        f"Мы начислили тебе {bonus_amount} бонусов — приходи играть, будем ждать!"
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
                description=f"Авторассылка: {setting.get('title') or code}",
                status="done",
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
    club_id = int(setting["club_id"])
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


def process_auto_mailings() -> dict:
    conn = get_db_connection()
    total_created = 0
    processed = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM auto_mailing_settings
                WHERE is_enabled = 1
                ORDER BY club_id, id
                """
            )
            settings = cur.fetchall()

        for setting in settings:
            code = setting.get("code")
            if code == "inactive_14_bonus":
                created = process_inactive_14_bonus(conn, setting)
                total_created += created
                processed.append({"club_id": setting["club_id"], "code": code, "recipients": created})
            elif code == "first_visit_survey":
                created = process_first_visit_survey(conn, setting)
                total_created += created
                processed.append({"club_id": setting["club_id"], "code": code, "recipients": created})

        return {"processed": processed, "recipients_created": total_created}
    finally:
        conn.close()


def main():
    result = process_auto_mailings()
    print(result)


if __name__ == "__main__":
    main()
