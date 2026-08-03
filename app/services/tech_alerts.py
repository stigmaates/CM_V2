from __future__ import annotations

import hashlib
import html
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from app.config import TECH_ALERT_BOT_TOKEN, TECH_ALERT_CHAT_ID, TECH_ALERT_PROXY_URL
from app.core import get_db_connection
from app.services.operational_alerts import get_operational_alerts

HttpPost = Callable[[str, dict[str, Any]], Any]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_operational_alert_notifications_table(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operational_alert_notifications (
            alert_key VARCHAR(191) PRIMARY KEY,
            severity VARCHAR(30) NOT NULL,
            code VARCHAR(80) NOT NULL,
            club_id INT NULL,
            message TEXT NULL,
            metadata_json JSON NULL,
            last_sent_at DATETIME NOT NULL,
            send_count INT NOT NULL DEFAULT 1,
            KEY idx_operational_alert_notifications_last_sent (last_sent_at),
            KEY idx_operational_alert_notifications_club_code (club_id, code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)


def critical_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [alert for alert in alerts if alert.get("severity") == "error"]


def build_alert_key(alert: dict[str, Any]) -> str:
    payload = {
        "code": alert.get("code"),
        "club_id": alert.get("club_id"),
        "job_type": alert.get("job_type"),
        "mailing_id": (alert.get("metadata") or {}).get("mailing_id"),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def format_tech_alert_message(alert: dict[str, Any]) -> str:
    lines = [
        "<b>ClubModule: критическое предупреждение</b>",
        f"Код: <code>{html.escape(str(alert.get('code') or 'unknown'))}</code>",
    ]
    if alert.get("club_id") is not None:
        club = f"Клуб: <code>{html.escape(str(alert['club_id']))}</code>"
        if alert.get("club_name"):
            club += f" · {html.escape(str(alert['club_name']))}"
        lines.append(club)
    if alert.get("job_type"):
        lines.append(f"Задача: <code>{html.escape(str(alert['job_type']))}</code>")
    if alert.get("age_minutes") is not None:
        lines.append(f"Возраст: {int(alert['age_minutes'])} мин.")
    lines.append(f"Сообщение: {html.escape(str(alert.get('message') or ''))}")

    metadata = alert.get("metadata") or {}
    error_text = metadata.get("error_text")
    if error_text:
        lines.append(f"Ошибка: <code>{html.escape(str(error_text)[:800])}</code>")
    return "\n".join(lines)


def format_test_alert_message() -> str:
    return "\n".join(
        [
            "<b>ClubModule: тест технических алертов</b>",
            "Если ты видишь это сообщение, Telegram-алерты настроены корректно.",
        ]
    )


def _should_send(cursor, alert_key: str, *, now: datetime, cooldown_minutes: int) -> bool:
    cursor.execute(
        "SELECT last_sent_at FROM operational_alert_notifications WHERE alert_key = %s",
        (alert_key,),
    )
    row = cursor.fetchone()
    if not row:
        return True
    last_sent_at = row.get("last_sent_at")
    if not last_sent_at:
        return True
    return last_sent_at <= now - timedelta(minutes=cooldown_minutes)


def _record_sent(cursor, alert: dict[str, Any], alert_key: str, message: str, *, now: datetime) -> None:
    cursor.execute(
        """
        INSERT INTO operational_alert_notifications (
            alert_key, severity, code, club_id, message, metadata_json, last_sent_at, send_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            severity = VALUES(severity),
            code = VALUES(code),
            club_id = VALUES(club_id),
            message = VALUES(message),
            metadata_json = VALUES(metadata_json),
            last_sent_at = VALUES(last_sent_at),
            send_count = send_count + 1
        """,
        (
            alert_key,
            alert.get("severity") or "error",
            alert.get("code") or "unknown",
            alert.get("club_id"),
            message,
            json.dumps(alert.get("metadata") or {}, ensure_ascii=True, default=str),
            now,
        ),
    )


def send_telegram_message(
    text: str,
    *,
    token: str | None = None,
    chat_id: str | None = None,
    http_post: HttpPost | None = None,
) -> tuple[bool, str | None]:
    token = (token if token is not None else TECH_ALERT_BOT_TOKEN).strip()
    chat_id = (chat_id if chat_id is not None else TECH_ALERT_CHAT_ID).strip()
    if not token:
        return False, "TECH_ALERT_BOT_TOKEN is empty"
    if not chat_id:
        return False, "TECH_ALERT_CHAT_ID is empty"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        if http_post:
            response = http_post(url, payload)
        else:
            client_kwargs: dict[str, Any] = {"timeout": 20.0}
            if TECH_ALERT_PROXY_URL:
                client_kwargs["proxy"] = TECH_ALERT_PROXY_URL
            with httpx.Client(**client_kwargs) as client:
                response = client.post(url, json=payload)
        data = response.json()
        if getattr(response, "status_code", 200) >= 400 or not data.get("ok"):
            return False, str(data)
        return True, None
    except Exception as exc:
        return False, str(exc)


def send_operational_alerts(
    alerts: list[dict[str, Any]] | None = None,
    *,
    cooldown_minutes: int = 60,
    dry_run: bool = False,
    http_post: HttpPost | None = None,
) -> dict[str, Any]:
    alerts = critical_alerts(alerts if alerts is not None else get_operational_alerts())
    result: dict[str, Any] = {
        "critical": len(alerts),
        "sent": 0,
        "skipped": 0,
        "errors": [],
        "messages": [],
    }
    if not alerts:
        return result

    now = _utcnow()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_operational_alert_notifications_table(cursor)
            for alert in alerts:
                alert_key = build_alert_key(alert)
                message = format_tech_alert_message(alert)
                if not _should_send(cursor, alert_key, now=now, cooldown_minutes=cooldown_minutes):
                    result["skipped"] += 1
                    continue
                result["messages"].append(message)
                if dry_run:
                    result["sent"] += 1
                    continue
                sent, error_text = send_telegram_message(message, http_post=http_post)
                if sent:
                    _record_sent(cursor, alert, alert_key, message, now=now)
                    conn.commit()
                    result["sent"] += 1
                else:
                    result["errors"].append(error_text or "unknown send error")
        return result
    finally:
        conn.close()


def send_test_alert(*, http_post: HttpPost | None = None) -> tuple[bool, str | None]:
    return send_telegram_message(format_test_alert_message(), http_post=http_post)
