from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables


_referral_tables_ready = False


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith(("7", "8")):
        digits = "7" + digits[-10:]
    return digits


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


def ensure_referral_tables(cursor) -> None:
    global _referral_tables_ready
    if _referral_tables_ready:
        return

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS club_referral_settings (
            club_id INT NOT NULL PRIMARY KEY,
            is_enabled TINYINT(1) NOT NULL DEFAULT 0,
            required_hours DECIMAL(8,2) NOT NULL DEFAULT 3.00,
            inviter_bonus INT NOT NULL DEFAULT 300,
            invited_bonus INT NOT NULL DEFAULT 150,
            rules_text TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_links (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            invited_guest_id INT NOT NULL,
            referrer_guest_id INT NOT NULL,
            invited_phone VARCHAR(40) NULL,
            referrer_phone VARCHAR(40) NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending_confirmation',
            requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            confirmed_at DATETIME NULL,
            rewarded_at DATETIME NULL,
            inviter_bonus_awarded INT NOT NULL DEFAULT 0,
            invited_bonus_awarded INT NOT NULL DEFAULT 0,
            error_text TEXT NULL,
            UNIQUE KEY uq_referral_invited_guest (club_id, invited_guest_id),
            KEY idx_referral_referrer (club_id, referrer_guest_id, status),
            KEY idx_referral_status (status),
            KEY idx_referral_requested (club_id, requested_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    # Compatibility for databases created by early test versions.
    for table, columns in {
        "club_referral_settings": {
            "is_enabled": "TINYINT(1) NOT NULL DEFAULT 0",
            "required_hours": "DECIMAL(8,2) NOT NULL DEFAULT 3.00",
            "inviter_bonus": "INT NOT NULL DEFAULT 300",
            "invited_bonus": "INT NOT NULL DEFAULT 150",
            "rules_text": "TEXT NULL",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        },
        "referral_links": {
            "invited_phone": "VARCHAR(40) NULL",
            "referrer_phone": "VARCHAR(40) NULL",
            "status": "VARCHAR(40) NOT NULL DEFAULT 'pending_confirmation'",
            "requested_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "confirmed_at": "DATETIME NULL",
            "rewarded_at": "DATETIME NULL",
            "inviter_bonus_awarded": "INT NOT NULL DEFAULT 0",
            "invited_bonus_awarded": "INT NOT NULL DEFAULT 0",
            "error_text": "TEXT NULL",
        },
    }.items():
        for col, ddl in columns.items():
            _ensure_column(cursor, table, col, ddl)

    _referral_tables_ready = True


def _default_rules_text() -> str:
    return (
        "Новый гость указывает телефон друга. Друг подтверждает заявку в своём кабинете, "
        "вводя телефон нового гостя. Бонусы начисляются обоим после того, как новый гость "
        "отыграет нужное количество часов."
    )


def get_referral_settings(club_id: int) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute(
                """
                INSERT IGNORE INTO club_referral_settings
                    (club_id, is_enabled, required_hours, inviter_bonus, invited_bonus, rules_text)
                VALUES (%s, 0, 3.00, 300, 150, %s)
                """,
                (club_id, _default_rules_text()),
            )
            cursor.execute(
                """
                SELECT club_id, is_enabled, required_hours, inviter_bonus, invited_bonus, rules_text
                FROM club_referral_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            row = cursor.fetchone() or {}
        conn.commit()
        return {
            "club_id": int(row.get("club_id") or club_id),
            "is_enabled": bool(row.get("is_enabled")),
            "required_hours": float(row.get("required_hours") or 0),
            "inviter_bonus": int(row.get("inviter_bonus") or 0),
            "invited_bonus": int(row.get("invited_bonus") or 0),
            "rules_text": row.get("rules_text") or _default_rules_text(),
        }
    finally:
        conn.close()


def save_referral_settings(
    club_id: int,
    is_enabled: bool,
    required_hours: float,
    inviter_bonus: int,
    invited_bonus: int,
    rules_text: str | None = None,
) -> None:
    required_hours = max(float(required_hours or 0), 0.0)
    inviter_bonus = max(int(inviter_bonus or 0), 0)
    invited_bonus = max(int(invited_bonus or 0), 0)
    rules_text = (rules_text or _default_rules_text()).strip()

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute(
                """
                INSERT INTO club_referral_settings
                    (club_id, is_enabled, required_hours, inviter_bonus, invited_bonus, rules_text)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_enabled = VALUES(is_enabled),
                    required_hours = VALUES(required_hours),
                    inviter_bonus = VALUES(inviter_bonus),
                    invited_bonus = VALUES(invited_bonus),
                    rules_text = VALUES(rules_text),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (club_id, 1 if is_enabled else 0, required_hours, inviter_bonus, invited_bonus, rules_text),
            )
        conn.commit()
    finally:
        conn.close()


def _guest_session_count(cursor, club_id: int, guest_id: int) -> int:
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM guest_sessions WHERE club_id = %s AND guest_id = %s",
        (club_id, guest_id),
    )
    return int((cursor.fetchone() or {}).get("cnt") or 0)


def _find_guest_by_phone(cursor, club_id: int, phone: str) -> dict[str, Any] | None:
    normalized = normalize_phone(phone)
    if len(normalized) < 10:
        return None
    cursor.execute(
        """
        SELECT club_id, guest_id, fio, phone
        FROM guests
        WHERE club_id = %s
          AND phone IS NOT NULL
          AND phone <> ''
        """,
        (club_id,),
    )
    matches = []
    for row in cursor.fetchall() or []:
        if normalize_phone(row.get("phone")) == normalized:
            matches.append(row)
    if len(matches) != 1:
        return None
    return matches[0]


def _format_status(status: str) -> str:
    return {
        "pending_confirmation": "ожидает подтверждения другом",
        "confirmed": "подтверждено, ждём часы",
        "rewarded": "бонусы начислены",
        "cancelled": "отменено",
    }.get(status or "", status or "—")


def _invited_hours_after(cursor, club_id: int, invited_guest_id: int, requested_at) -> float:
    cursor.execute(
        """
        SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE, date_start, date_stop)), 0) AS minutes
        FROM guest_sessions
        WHERE club_id = %s
          AND guest_id = %s
          AND date_start IS NOT NULL
          AND date_stop IS NOT NULL
          AND date_start >= %s
        """,
        (club_id, invited_guest_id, requested_at),
    )
    minutes = int((cursor.fetchone() or {}).get("minutes") or 0)
    return round(minutes / 60, 2)


def _decorate_link(cursor, row: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    hours_played = _invited_hours_after(cursor, int(row["club_id"]), int(row["invited_guest_id"]), row["requested_at"])
    required = float(settings.get("required_hours") or 0)
    item = dict(row)
    item["status_label"] = _format_status(item.get("status"))
    item["hours_played"] = hours_played
    item["hours_left"] = max(round(required - hours_played, 2), 0)
    item["progress_percent"] = int(round(min(hours_played / required, 1) * 100)) if required > 0 else 100
    return item


def _current_month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    return month_start, month_end


def process_referral_rewards(club_id: int) -> int:
    settings = get_referral_settings(club_id)
    if not settings.get("is_enabled"):
        return 0

    awarded = 0
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            ensure_cm_bonus_tables(cursor)
            cursor.execute(
                """
                SELECT *
                FROM referral_links
                WHERE club_id = %s
                  AND status = 'confirmed'
                FOR UPDATE
                """,
                (club_id,),
            )
            rows = cursor.fetchall() or []
            for row in rows:
                hours_played = _invited_hours_after(cursor, club_id, int(row["invited_guest_id"]), row["requested_at"])
                if hours_played + 1e-9 < float(settings.get("required_hours") or 0):
                    continue

                link_id = int(row["id"])
                inviter_bonus = int(settings.get("inviter_bonus") or 0)
                invited_bonus = int(settings.get("invited_bonus") or 0)
                if inviter_bonus > 0:
                    add_cm_bonus_transaction(
                        cursor=cursor,
                        guest_id=int(row["referrer_guest_id"]),
                        club_id=club_id,
                        amount=inviter_bonus,
                        source_type="referral_inviter",
                        source_id=str(link_id),
                        description=f"Реферальная программа: друг отыграл {settings.get('required_hours')} ч.",
                    )
                if invited_bonus > 0:
                    add_cm_bonus_transaction(
                        cursor=cursor,
                        guest_id=int(row["invited_guest_id"]),
                        club_id=club_id,
                        amount=invited_bonus,
                        source_type="referral_invited",
                        source_id=str(link_id),
                        description="Реферальная программа: бонус новому гостю",
                    )
                cursor.execute(
                    """
                    UPDATE referral_links
                    SET status = 'rewarded',
                        rewarded_at = %s,
                        inviter_bonus_awarded = %s,
                        invited_bonus_awarded = %s
                    WHERE id = %s
                    """,
                    (datetime.utcnow(), inviter_bonus, invited_bonus, link_id),
                )
                awarded += 1
        conn.commit()
        return awarded
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def submit_referral(club_id: int, invited_guest_id: int, referrer_phone: str) -> dict[str, Any]:
    settings = get_referral_settings(club_id)
    if not settings.get("is_enabled"):
        raise ValueError("Реферальная программа сейчас выключена.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute(
                "SELECT club_id, guest_id, fio, phone FROM guests WHERE club_id=%s AND guest_id=%s LIMIT 1",
                (club_id, invited_guest_id),
            )
            invited = cursor.fetchone()
            if not invited:
                raise ValueError("Гость не найден.")
            if _guest_session_count(cursor, club_id, invited_guest_id) > 0:
                raise ValueError("Указать друга можно только до первого визита.")
            cursor.execute(
                "SELECT id FROM referral_links WHERE club_id=%s AND invited_guest_id=%s LIMIT 1",
                (club_id, invited_guest_id),
            )
            if cursor.fetchone():
                raise ValueError("Ты уже отправлял реферальную заявку.")

            referrer = _find_guest_by_phone(cursor, club_id, referrer_phone)
            if not referrer:
                raise ValueError("Не нашли друга с таким телефоном в этом клубе.")
            if int(referrer["guest_id"]) == int(invited_guest_id):
                raise ValueError("Нельзя указать свой собственный номер.")

            cursor.execute(
                """
                INSERT INTO referral_links
                    (club_id, invited_guest_id, referrer_guest_id, invited_phone, referrer_phone, status, requested_at)
                VALUES (%s, %s, %s, %s, %s, 'pending_confirmation', %s)
                """,
                (
                    club_id,
                    invited_guest_id,
                    int(referrer["guest_id"]),
                    invited.get("phone"),
                    referrer.get("phone"),
                    datetime.utcnow(),
                ),
            )
            link_id = cursor.lastrowid
        conn.commit()
        return {"ok": True, "id": link_id, "message": "Заявка отправлена другу на подтверждение."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def confirm_referral(club_id: int, referrer_guest_id: int, request_id: int, invited_phone: str) -> dict[str, Any]:
    settings = get_referral_settings(club_id)
    if not settings.get("is_enabled"):
        raise ValueError("Реферальная программа сейчас выключена.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute(
                """
                SELECT * FROM referral_links
                WHERE id=%s AND club_id=%s AND referrer_guest_id=%s
                LIMIT 1
                """,
                (request_id, club_id, referrer_guest_id),
            )
            link = cursor.fetchone()
            if not link:
                raise ValueError("Заявка не найдена.")
            if link.get("status") != "pending_confirmation":
                raise ValueError("Эта заявка уже обработана.")

            invited = _find_guest_by_phone(cursor, club_id, invited_phone)
            if not invited or int(invited["guest_id"]) != int(link["invited_guest_id"]):
                raise ValueError("Телефон не совпадает с новым гостем, который указал тебя другом.")

            cursor.execute(
                """
                UPDATE referral_links
                SET status='confirmed', confirmed_at=%s
                WHERE id=%s
                """,
                (datetime.utcnow(), request_id),
            )
        conn.commit()
        # Try to award immediately in case hours were already synced.
        process_referral_rewards(club_id)
        return {"ok": True, "message": "Заявка подтверждена. Бонусы начислятся после выполнения условия по часам."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_guest_referral_context(guest_id: int, club_id: int) -> dict[str, Any]:
    process_referral_rewards(club_id)
    settings = get_referral_settings(club_id)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            sessions_count = _guest_session_count(cursor, club_id, guest_id)
            cursor.execute(
                """
                SELECT rl.*, rg.fio AS referrer_name, ig.fio AS invited_name
                FROM referral_links rl
                LEFT JOIN guests rg ON rg.club_id=rl.club_id AND rg.guest_id=rl.referrer_guest_id
                LEFT JOIN guests ig ON ig.club_id=rl.club_id AND ig.guest_id=rl.invited_guest_id
                WHERE rl.club_id=%s AND rl.invited_guest_id=%s
                LIMIT 1
                """,
                (club_id, guest_id),
            )
            outgoing_row = cursor.fetchone()
            outgoing = _decorate_link(cursor, outgoing_row, settings) if outgoing_row else None

            cursor.execute(
                """
                SELECT rl.*, ig.fio AS invited_name, ig.phone AS invited_phone, rg.fio AS referrer_name
                FROM referral_links rl
                LEFT JOIN guests ig ON ig.club_id=rl.club_id AND ig.guest_id=rl.invited_guest_id
                LEFT JOIN guests rg ON rg.club_id=rl.club_id AND rg.guest_id=rl.referrer_guest_id
                WHERE rl.club_id=%s AND rl.referrer_guest_id=%s
                ORDER BY rl.requested_at DESC, rl.id DESC
                LIMIT 20
                """,
                (club_id, guest_id),
            )
            incoming_rows = cursor.fetchall() or []
            incoming = [_decorate_link(cursor, row, settings) for row in incoming_rows]

            month_start, month_end = _current_month_bounds()
            cursor.execute(
                """
                SELECT
                    rl.referrer_guest_id AS guest_id,
                    g.fio,
                    COUNT(*) AS invited_count,
                    COUNT(CASE WHEN rl.status IN ('confirmed','rewarded') THEN 1 END) AS confirmed_count,
                    COUNT(CASE WHEN rl.status='rewarded' THEN 1 END) AS rewarded_count,
                    COALESCE(SUM(rl.inviter_bonus_awarded), 0) AS bonus_earned
                FROM referral_links rl
                JOIN guests g ON g.club_id=rl.club_id AND g.guest_id=rl.referrer_guest_id
                WHERE rl.club_id=%s
                  AND rl.requested_at >= %s
                  AND rl.requested_at < %s
                GROUP BY rl.referrer_guest_id, g.fio
                HAVING invited_count > 0
                ORDER BY invited_count DESC, rewarded_count DESC, bonus_earned DESC, g.fio ASC
                """,
                (club_id, month_start, month_end),
            )
            leaderboard_month = cursor.fetchall() or []

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS invited_total,
                    COUNT(CASE WHEN status='rewarded' THEN 1 END) AS rewarded_total,
                    COALESCE(SUM(inviter_bonus_awarded), 0) AS bonus_earned
                FROM referral_links
                WHERE club_id=%s AND referrer_guest_id=%s
                """,
                (club_id, guest_id),
            )
            own_stats = cursor.fetchone() or {}

        return {
            "settings": settings,
            "is_enabled": bool(settings.get("is_enabled")),
            "can_submit": bool(settings.get("is_enabled")) and sessions_count == 0 and outgoing is None,
            "sessions_count": sessions_count,
            "outgoing": outgoing,
            "incoming": incoming,
            "pending_incoming": [x for x in incoming if x.get("status") == "pending_confirmation"],
            "leaderboard": leaderboard_month[:3],
            "leaderboard_full": leaderboard_month,
            "leaderboard_month_label": month_start.strftime("%m.%Y"),
            "own_stats": own_stats,
        }
    finally:
        conn.close()


def get_dashboard_referral_stats(club_id: int, period_days: int = 30) -> dict[str, Any]:
    process_referral_rewards(club_id)
    now = datetime.now()
    from datetime import timedelta
    start = now.replace(microsecond=0) - timedelta(days=period_days)
    end = now.replace(microsecond=0)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_referral_tables(cursor)
            cursor.execute(
                """
                SELECT id, invited_guest_id, requested_at
                FROM referral_links
                WHERE club_id=%s
                  AND status IN ('confirmed','rewarded')
                  AND requested_at >= %s
                  AND requested_at < %s
                """,
                (club_id, start, end),
            )
            rows = cursor.fetchall() or []
            invited_ids = [int(r["invited_guest_id"]) for r in rows]
            if not invited_ids:
                return {
                    "period_days": period_days,
                    "referred_guests": 0,
                    "returned_after_first": 0,
                    "wheel_spun": 0,
                    "completed_mission": 0,
                }
            placeholders = ",".join(["%s"] * len(invited_ids))
            params = [club_id] + invited_ids
            cursor.execute(
                f"""
                SELECT guest_id, COUNT(*) AS cnt
                FROM guest_sessions
                WHERE club_id=%s AND guest_id IN ({placeholders})
                GROUP BY guest_id
                """,
                params,
            )
            session_counts = {int(r["guest_id"]): int(r.get("cnt") or 0) for r in cursor.fetchall() or []}
            cursor.execute(
                f"""
                SELECT DISTINCT guest_id
                FROM guest_wheel_spins
                WHERE club_id=%s AND guest_id IN ({placeholders})
                """,
                params,
            )
            wheel_ids = {int(r["guest_id"]) for r in cursor.fetchall() or []}

        # Mission calculation uses existing service rules. Kept outside DB cursor because it opens its own connections.
        from app.services.missions import get_guest_missions_with_progress
        completed_mission = 0
        for gid in invited_ids:
            try:
                if any(m.get("is_completed") for m in get_guest_missions_with_progress(gid, club_id)):
                    completed_mission += 1
            except Exception:
                pass

        return {
            "period_days": period_days,
            "referred_guests": len(invited_ids),
            "returned_after_first": sum(1 for gid in invited_ids if session_counts.get(gid, 0) >= 2),
            "wheel_spun": len(wheel_ids),
            "completed_mission": completed_mission,
        }
    finally:
        conn.close()
