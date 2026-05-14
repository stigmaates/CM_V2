import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

from app.core import get_db_connection
from app.services.mailing import (
    create_mailing_for_recipients,
    get_inactive_auto_mailing_recipients,
)
from scripts.process_mailings import process_one_mailing


def process_inactive_14_bonus(conn, setting: dict) -> int:
    club_id = setting["club_id"]
    code = setting["code"]
    days_inactive = int(setting.get("days_inactive") or 14)
    repeat_after_days = int(setting.get("repeat_after_days") or 30)
    message_text = setting.get("message_text") or "Привет! Тебя давно не было в клубе 😔\n\nМы начислили тебе 200 бонусов — приходи играть, будем ждать!"

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
            "repeat_after_days": repeat_after_days,
        },
    )
    conn.commit()

    mailing_id = mailing["mailing_id"]
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

        return {"processed": processed, "recipients_created": total_created}
    finally:
        conn.close()


def main():
    result = process_auto_mailings()
    print(result)


if __name__ == "__main__":
    main()
