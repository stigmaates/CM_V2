from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.config import TOPUP_BONUS_MAX_AMOUNT
from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction
from app.services.wheel import add_guest_token_transaction

REWARD_TYPES = {"cm_bonus", "tokens"}

DEFAULT_TOPUP_BONUS_MESSAGE = (
    "{first_name}, ты пополнил баланс на {topup_amount} ₽. "
    "За пополнение от {min_sum} ₽ мы дарим тебе {reward_amount} {reward_name}!"
)

TOPUP_BONUS_VARIABLES = (
    ("first_name", "Имя"),
    ("club_name", "Клуб"),
    ("topup_amount", "Сумма пополнения"),
    ("min_sum", "Порог правила"),
    ("reward_amount", "Начислено"),
    ("reward_name", "Тип награды"),
    ("bonus_amount", "Начислено (старый формат)"),
    ("cm_bonus_balance", "Баланс КБ"),
    ("token_balance", "Баланс жетонов"),
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TOPUP_BONUS_DUPLICATE_WINDOW = timedelta(hours=1)


def _moscow_now() -> datetime:
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)


def _looks_like_patronymic(value: str) -> bool:
    return (value or "").lower().endswith(("ич", "вна", "чна", "инична", "овна", "евна"))


def _looks_like_surname(value: str) -> bool:
    return (
        (value or "")
        .lower()
        .endswith(("ов", "ова", "ев", "ева", "ёв", "ёва", "ин", "ина", "ын", "ына", "ский", "ская", "цкий", "цкая"))
    )


def _first_name(fio: str | None) -> str:
    value = (fio or "").strip()
    if not value:
        return "Гость"
    parts = value.split()
    if len(parts) >= 3:
        if _looks_like_patronymic(parts[1]):
            return parts[0]
        if _looks_like_patronymic(parts[2]):
            return parts[1]
    if len(parts) == 2 and _looks_like_surname(parts[0]):
        return parts[1]
    return parts[0]


def _format_money(value: Any) -> str:
    amount = Decimal(str(value or 0))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return format(amount.normalize(), "f")


def select_topup_bonus_rule(rules: list[dict[str, Any]], amount: Any) -> dict[str, Any] | None:
    value = Decimal(str(amount or 0))
    eligible = [rule for rule in rules if Decimal(str(rule.get("min_amount") or 0)) <= value]
    if not eligible:
        return None
    return max(eligible, key=lambda rule: Decimal(str(rule.get("min_amount") or 0)))


def render_topup_bonus_message(template: str, values: dict[str, Any]) -> str:
    reward_type = values.get("reward_type") or "cm_bonus"
    reward_amount = int(values.get("reward_amount") or values.get("bonus_amount") or 0)
    replacements = {
        "first_name": _first_name(values.get("fio")),
        "club_name": values.get("club_name") or "",
        "topup_amount": _format_money(values.get("topup_amount")),
        "min_sum": _format_money(values.get("min_amount")),
        "reward_amount": reward_amount,
        "reward_name": "КБ" if reward_type == "cm_bonus" else "жет.",
        "bonus_amount": reward_amount,
        "cm_bonus_balance": int(values.get("cm_bonus_balance") or 0),
        "token_balance": int(values.get("token_balance") or 0),
    }

    def replace(match):
        key = match.group(1)
        return str(replacements.get(key, match.group(0)))

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, template or "")


def _resolve_enabled_at(
    existing_settings: dict[str, Any] | None,
    *,
    is_enabled: bool,
    now: datetime,
) -> datetime | None:
    if not is_enabled:
        return None
    if existing_settings and existing_settings.get("is_enabled") and existing_settings.get("enabled_at"):
        return existing_settings["enabled_at"]
    return now


def get_topup_bonus_settings(club_id: int) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT club_id, is_enabled, message_template, enabled_at
                FROM club_topup_bonus_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            settings = cursor.fetchone() or {
                "club_id": club_id,
                "is_enabled": 0,
                "message_template": DEFAULT_TOPUP_BONUS_MESSAGE,
                "enabled_at": None,
            }
            cursor.execute(
                """
                SELECT id, min_amount, bonus_amount, reward_type, sort_order
                FROM club_topup_bonus_rules
                WHERE club_id = %s
                ORDER BY min_amount, id
                """,
                (club_id,),
            )
            settings["rules"] = cursor.fetchall()
            return settings
    finally:
        conn.close()


def save_topup_bonus_settings(
    club_id: int,
    *,
    is_enabled: bool,
    message_template: str,
    rules: list[dict[str, Any]],
) -> None:
    normalized_rules = []
    seen_thresholds = set()
    for index, rule in enumerate(rules):
        min_amount = Decimal(str(rule.get("min_amount") or 0))
        bonus_amount = int(rule.get("bonus_amount") or 0)
        reward_type = str(rule.get("reward_type") or "cm_bonus")
        if min_amount <= 0 or bonus_amount <= 0:
            raise ValueError("Порог пополнения и количество награды должны быть больше нуля")
        if reward_type not in REWARD_TYPES:
            raise ValueError("Неизвестный тип награды")
        if min_amount >= Decimal(str(TOPUP_BONUS_MAX_AMOUNT)):
            raise ValueError(f"Порог должен быть меньше {TOPUP_BONUS_MAX_AMOUNT} ₽")
        if min_amount in seen_thresholds:
            raise ValueError("Пороги пополнений не должны повторяться")
        seen_thresholds.add(min_amount)
        normalized_rules.append((club_id, min_amount, bonus_amount, reward_type, index * 10))

    if is_enabled and not normalized_rules:
        raise ValueError("Добавь хотя бы одно правило начисления")
    message_template = (message_template or "").strip()
    if not message_template:
        raise ValueError("Сообщение гостю не может быть пустым")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT is_enabled, enabled_at
                FROM club_topup_bonus_settings
                WHERE club_id = %s
                FOR UPDATE
                """,
                (club_id,),
            )
            enabled_at = _resolve_enabled_at(
                cursor.fetchone(),
                is_enabled=is_enabled,
                now=_moscow_now(),
            )
            cursor.execute(
                """
                INSERT INTO club_topup_bonus_settings (
                    club_id, is_enabled, message_template, enabled_at
                ) VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_enabled = VALUES(is_enabled),
                    message_template = VALUES(message_template),
                    enabled_at = VALUES(enabled_at),
                    updated_at = NOW()
                """,
                (
                    club_id,
                    int(is_enabled),
                    message_template,
                    enabled_at,
                ),
            )
            cursor.execute("DELETE FROM club_topup_bonus_rules WHERE club_id = %s", (club_id,))
            if normalized_rules:
                cursor.executemany(
                    """
                    INSERT INTO club_topup_bonus_rules (
                        club_id, min_amount, bonus_amount, reward_type, sort_order
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    normalized_rules,
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_welcome_reward_settings(club_id: int) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT welcome_reward_enabled, welcome_cm_bonus_amount, welcome_token_amount
                FROM club_topup_bonus_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            return cursor.fetchone() or {
                "welcome_reward_enabled": 1,
                "welcome_cm_bonus_amount": 0,
                "welcome_token_amount": 1,
            }
    finally:
        conn.close()


def save_welcome_reward_settings(
    club_id: int,
    *,
    is_enabled: bool,
    cm_bonus_amount: int,
    token_amount: int,
) -> None:
    cm_bonus_amount = int(cm_bonus_amount or 0)
    token_amount = int(token_amount or 0)
    if cm_bonus_amount < 0 or token_amount < 0:
        raise ValueError("Количество награды не может быть отрицательным")
    if is_enabled and cm_bonus_amount == 0 and token_amount == 0:
        raise ValueError("Выберите хотя бы один тип приветственной награды")

    legacy_type = "tokens" if token_amount > 0 else "cm_bonus"
    legacy_amount = token_amount if token_amount > 0 else cm_bonus_amount
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO club_topup_bonus_settings (
                    club_id, is_enabled, message_template, enabled_at,
                    welcome_reward_enabled, welcome_reward_type, welcome_reward_amount,
                    welcome_cm_bonus_amount, welcome_token_amount
                ) VALUES (%s, 0, %s, NULL, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    welcome_reward_enabled = VALUES(welcome_reward_enabled),
                    welcome_reward_type = VALUES(welcome_reward_type),
                    welcome_reward_amount = VALUES(welcome_reward_amount),
                    welcome_cm_bonus_amount = VALUES(welcome_cm_bonus_amount),
                    welcome_token_amount = VALUES(welcome_token_amount),
                    updated_at = NOW()
                """,
                (
                    club_id,
                    DEFAULT_TOPUP_BONUS_MESSAGE,
                    int(is_enabled),
                    legacy_type,
                    legacy_amount,
                    cm_bonus_amount,
                    token_amount,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_enabled_club(cursor, club_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT s.club_id, s.message_template, s.enabled_at, c.name AS club_name
        FROM club_topup_bonus_settings s
        JOIN clubs c ON c.club_id = s.club_id
        WHERE s.club_id = %s AND s.is_enabled = 1 AND c.service_enabled = 1
        LIMIT 1
        """,
        (club_id,),
    )
    return cursor.fetchone()


def _claim_topup_bonus_award(
    cursor,
    *,
    club_id: int,
    topup: dict[str, Any],
    rule: dict[str, Any],
    awarded_at: datetime,
) -> str:
    """Claim one reward per equal guest topup amount inside the cooldown window."""
    window_start = topup["topup_at"] - TOPUP_BONUS_DUPLICATE_WINDOW
    window_end = topup["topup_at"] + TOPUP_BONUS_DUPLICATE_WINDOW
    cursor.execute(
        """
        SELECT a.id
        FROM guest_topup_bonus_awards a
        JOIN guest_balance_topups rewarded_topup
          ON rewarded_topup.club_id = a.club_id
         AND rewarded_topup.topup_id = a.topup_id
         AND rewarded_topup.guest_id = a.guest_id
        WHERE a.club_id = %s
          AND a.guest_id = %s
          AND a.status = 'awarded'
          AND rewarded_topup.amount = %s
          AND rewarded_topup.topup_at >= %s
          AND rewarded_topup.topup_at <= %s
        LIMIT 1
        """,
        (
            club_id,
            topup["guest_id"],
            topup["amount"],
            window_start,
            window_end,
        ),
    )
    duplicate_award = cursor.fetchone()
    status = "skipped_duplicate" if duplicate_award else "awarded"
    delivery_status = "skipped" if duplicate_award else ("pending" if topup.get("telegram_id") else "no_telegram")
    bonus_amount = 0 if duplicate_award else int(rule["bonus_amount"])
    cursor.execute(
        """
        INSERT IGNORE INTO guest_topup_bonus_awards (
            club_id, topup_id, guest_id, rule_id, topup_amount,
            bonus_amount, reward_type, status, delivery_status, telegram_id, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            club_id,
            topup["topup_id"],
            topup["guest_id"],
            rule["id"],
            topup["amount"],
            bonus_amount,
            rule["reward_type"],
            status,
            delivery_status,
            topup.get("telegram_id"),
            awarded_at,
        ),
    )
    if cursor.rowcount == 0:
        return "exists"
    return "duplicate" if duplicate_award else "awarded"


def process_topup_bonus_awards(
    club_id: int,
    *,
    send_message: Callable[[int, str], tuple[bool, str | None]] | None = None,
    limit: int = 500,
) -> dict[str, int]:
    conn = get_db_connection()
    awarded = sent = failed = skipped = 0
    try:
        with conn.cursor() as cursor:
            settings = _load_enabled_club(cursor, club_id)
            if not settings or not settings.get("enabled_at"):
                return {"awarded": 0, "sent": 0, "failed": 0, "skipped": 0}
            cursor.execute(
                """
                SELECT id, min_amount, bonus_amount, reward_type
                FROM club_topup_bonus_rules
                WHERE club_id = %s
                ORDER BY min_amount
                """,
                (club_id,),
            )
            rules = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    t.topup_id, t.guest_id, t.amount, t.topup_at,
                    g.fio, g.telegram_id
                FROM guest_balance_topups t
                JOIN guests g ON g.club_id = t.club_id AND g.guest_id = t.guest_id
                LEFT JOIN guest_topup_bonus_awards a
                  ON a.club_id = t.club_id AND a.topup_id = t.topup_id
                WHERE t.club_id = %s
                  AND t.topup_at >= %s
                  AND t.amount >= (
                      SELECT MIN(r.min_amount)
                      FROM club_topup_bonus_rules r
                      WHERE r.club_id = t.club_id
                  )
                  AND t.amount < %s
                  AND a.id IS NULL
                ORDER BY t.topup_at, t.topup_id
                LIMIT %s
                """,
                (club_id, settings["enabled_at"], TOPUP_BONUS_MAX_AMOUNT, limit),
            )
            candidates = cursor.fetchall()

        for topup in candidates:
            rule = select_topup_bonus_rule(rules, topup["amount"])
            if not rule:
                skipped += 1
                continue
            try:
                with conn.cursor() as cursor:
                    awarded_at = _moscow_now()
                    claim_status = _claim_topup_bonus_award(
                        cursor,
                        club_id=club_id,
                        topup=topup,
                        rule=rule,
                        awarded_at=awarded_at,
                    )
                    if claim_status == "exists":
                        continue
                    if claim_status == "duplicate":
                        conn.commit()
                        skipped += 1
                        continue
                    transaction_args = {
                        "cursor": cursor,
                        "guest_id": int(topup["guest_id"]),
                        "club_id": club_id,
                        "amount": int(rule["bonus_amount"]),
                        "source_type": "topup_reward",
                        "source_id": str(topup["topup_id"]),
                        "description": f"Награда за пополнение от {_format_money(rule['min_amount'])} ₽",
                    }
                    if rule["reward_type"] == "tokens":
                        changed = add_guest_token_transaction(**transaction_args)
                    else:
                        changed = add_cm_bonus_transaction(**transaction_args, created_at=awarded_at)
                    if not changed:
                        raise RuntimeError("Транзакция начисления уже существует")
                    cursor.execute(
                        """
                        SELECT
                            (SELECT balance FROM cm_bonus_balances WHERE club_id = %s AND guest_id = %s) AS cm_balance,
                            (SELECT balance FROM guest_wheel_token_balances WHERE club_id = %s AND guest_id = %s) AS token_balance
                        """,
                        (club_id, topup["guest_id"], club_id, topup["guest_id"]),
                    )
                    balances = cursor.fetchone() or {}
                    message = render_topup_bonus_message(
                        settings["message_template"],
                        {
                            "fio": topup.get("fio"),
                            "club_name": settings.get("club_name"),
                            "topup_amount": topup["amount"],
                            "min_amount": rule["min_amount"],
                            "bonus_amount": rule["bonus_amount"],
                            "reward_amount": rule["bonus_amount"],
                            "reward_type": rule["reward_type"],
                            "cm_bonus_balance": balances.get("cm_balance"),
                            "token_balance": balances.get("token_balance"),
                        },
                    )
                    cursor.execute(
                        """
                        UPDATE guest_topup_bonus_awards
                        SET message_text = %s
                        WHERE club_id = %s AND topup_id = %s
                        """,
                        (message, club_id, topup["topup_id"]),
                    )
                conn.commit()
                awarded += 1
            except Exception:
                conn.rollback()
                raise

        if send_message:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, telegram_id, message_text
                    FROM guest_topup_bonus_awards
                    WHERE club_id = %s AND delivery_status = 'pending'
                    ORDER BY id
                    LIMIT %s
                    """,
                    (club_id, limit),
                )
                pending = cursor.fetchall()
            for item in pending:
                ok, error_text = send_message(int(item["telegram_id"]), item.get("message_text") or "")
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE guest_topup_bonus_awards
                        SET delivery_status = %s,
                            error_text = %s,
                            sent_at = CASE WHEN %s = 'sent' THEN %s ELSE sent_at END
                        WHERE id = %s
                        """,
                        (
                            "sent" if ok else "failed",
                            error_text,
                            "sent" if ok else "failed",
                            _moscow_now(),
                            item["id"],
                        ),
                    )
                conn.commit()
                if ok:
                    sent += 1
                else:
                    failed += 1

        return {"awarded": awarded, "sent": sent, "failed": failed, "skipped": skipped}
    finally:
        conn.close()


def award_first_authorization_reward(guest_id: int, club_id: int) -> dict[str, Any] | None:
    """Award the configured welcome reward once across both reward ledgers."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT welcome_reward_enabled, welcome_cm_bonus_amount, welcome_token_amount
                FROM club_topup_bonus_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            settings = cursor.fetchone() or {
                "welcome_reward_enabled": 1,
                "welcome_cm_bonus_amount": 0,
                "welcome_token_amount": 1,
            }
            if not settings.get("welcome_reward_enabled"):
                return None

            cursor.execute(
                """
                SELECT 1 FROM guest_wheel_token_transactions
                WHERE club_id = %s AND guest_id = %s
                  AND source_type = 'first_authorization'
                  AND source_id IN ('welcome_token', 'welcome_reward')
                UNION ALL
                SELECT 1 FROM cm_bonus_transactions
                WHERE club_id = %s AND guest_id = %s
                  AND source_type = 'first_authorization'
                  AND source_id = 'welcome_reward'
                LIMIT 1
                """,
                (club_id, guest_id, club_id, guest_id),
            )
            if cursor.fetchone():
                return None

            cm_bonus_amount = int(settings.get("welcome_cm_bonus_amount") or 0)
            token_amount = int(settings.get("welcome_token_amount") or 0)
            common_args = {
                "cursor": cursor,
                "guest_id": guest_id,
                "club_id": club_id,
                "source_type": "first_authorization",
                "source_id": "welcome_reward",
                "description": "Приветственная награда за первую авторизацию в Cyber Bonus",
            }
            cm_bonus_inserted = False
            token_inserted = False
            if cm_bonus_amount > 0:
                cm_bonus_inserted = add_cm_bonus_transaction(amount=cm_bonus_amount, **common_args)
            if token_amount > 0:
                token_inserted = add_guest_token_transaction(amount=token_amount, **common_args)
        conn.commit()
        if not cm_bonus_inserted and not token_inserted:
            return None
        return {
            "cm_bonus_amount": cm_bonus_amount if cm_bonus_inserted else 0,
            "token_amount": token_amount if token_inserted else 0,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
