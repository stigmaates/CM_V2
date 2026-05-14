import os
import sys
import time
import pymysql
import httpx

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


from dotenv import load_dotenv
load_dotenv()

from app.core import get_db_connection
BOT_TOKEN = os.getenv("BOT_TOKEN")
TG_PROXY_URL = os.getenv("TG_PROXY_URL")

def tg_request(method: str, payload: dict | None = None, files=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    client_kwargs = {
        "timeout": 60,
    }

    if TG_PROXY_URL:
        client_kwargs["proxy"] = TG_PROXY_URL

    with httpx.Client(**client_kwargs) as client:
        if files:
            return client.post(url, data=payload, files=files)

        return client.post(url, json=payload)


def send_single_message(telegram_id: int, text: str, parse_mode: str, attachments: list[dict]):
    if not attachments:
        resp = tg_request(
            "sendMessage",
            {
                "chat_id": telegram_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": False,
            },
        )
        return resp

    first = attachments[0]
    file_type = first["file_type"]
    file_path = first["file_path"]

    if file_type == "photo":
        with open(file_path, "rb") as f:
            return tg_request(
                "sendPhoto",
                {
                    "chat_id": telegram_id,
                    "caption": text,
                    "parse_mode": parse_mode,
                },
                files={"photo": f},
            )

    if file_type == "video":
        with open(file_path, "rb") as f:
            return tg_request(
                "sendVideo",
                {
                    "chat_id": telegram_id,
                    "caption": text,
                    "parse_mode": parse_mode,
                },
                files={"video": f},
            )

    if file_type == "animation":
        with open(file_path, "rb") as f:
            return tg_request(
                "sendAnimation",
                {
                    "chat_id": telegram_id,
                    "caption": text,
                    "parse_mode": parse_mode,
                },
                files={"animation": f},
            )

    with open(file_path, "rb") as f:
        return tg_request(
            "sendDocument",
            {
                "chat_id": telegram_id,
                "caption": text,
                "parse_mode": parse_mode,
            },
            files={"document": f},
        )


def process_one_mailing(conn, mailing_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mailings
            SET status = 'in_progress', started_at = NOW()
            WHERE id = %s AND status = 'queued'
            """,
            (mailing_id,),
        )
        if cur.rowcount == 0:
            return

        cur.execute("SELECT * FROM mailings WHERE id = %s", (mailing_id,))
        mailing = cur.fetchone()

        cur.execute(
            """
            SELECT id, guest_id, telegram_id
            FROM mailing_recipients
            WHERE mailing_id = %s AND status = 'pending'
            ORDER BY id
            """,
            (mailing_id,),
        )
        recipients = cur.fetchall()

        cur.execute(
            """
            SELECT file_type, file_path, original_name
            FROM mailing_attachments
            WHERE mailing_id = %s
            ORDER BY id
            """,
            (mailing_id,),
        )
        attachments = cur.fetchall()

    success_count = 0
    failed_count = 0

    for rec in recipients:
        recipient_id = rec["id"]
        telegram_id = rec["telegram_id"]

        try:
            response = send_single_message(
                telegram_id=telegram_id,
                text=mailing["message_text"],
                parse_mode=mailing["parse_mode"],
                attachments=attachments,
            )
            ok = response.status_code == 200 and response.json().get("ok") is True

            with conn.cursor() as cur:
                if ok:
                    cur.execute(
                        """
                        UPDATE mailing_recipients
                        SET status = 'sent', sent_at = NOW(), error_text = NULL
                        WHERE id = %s
                        """,
                        (recipient_id,),
                    )
                    success_count += 1
                else:
                    error_text = response.text[:1000]
                    cur.execute(
                        """
                        UPDATE mailing_recipients
                        SET status = 'failed', error_text = %s
                        WHERE id = %s
                        """,
                        (error_text, recipient_id),
                    )
                    failed_count += 1

            conn.commit()
            time.sleep(0.08)

        except Exception as e:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mailing_recipients
                    SET status = 'failed', error_text = %s
                    WHERE id = %s
                    """,
                    (str(e)[:1000], recipient_id),
                )
            conn.commit()
            failed_count += 1
            time.sleep(0.15)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mailings
            SET
                status = 'completed',
                success_count = (
                    SELECT COUNT(*) FROM mailing_recipients
                    WHERE mailing_id = %s AND status = 'sent'
                ),
                failed_count = (
                    SELECT COUNT(*) FROM mailing_recipients
                    WHERE mailing_id = %s AND status = 'failed'
                ),
                finished_at = NOW()
            WHERE id = %s
            """,
            (mailing_id, mailing_id, mailing_id),
        )
    conn.commit()


def main():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mailings WHERE status = 'queued' ORDER BY id ASC")
            rows = cur.fetchall()

        for row in rows:
            process_one_mailing(conn, row["id"])

    finally:
        conn.close()


if __name__ == "__main__":
    main()