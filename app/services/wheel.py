import random
from datetime import date, datetime, timedelta
from typing import Any

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, award_cm_bonuses_for_wheel_prize, ensure_cm_bonus_tables
from app.services.missions import get_guest_missions_with_progress
from app.services.prize_claims import (
    create_prize_claim,
    ensure_prize_claim_tables,
    notify_prize_claim_admin_chat,
)

_token_tables_ready = False


_wheel_prize_bonus_columns_ready = False
_wheel_settings_display_columns_ready = False


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


def _ensure_index(cursor, table_name: str, index_name: str, ddl: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    row = cursor.fetchone() or {}
    if int(row.get("cnt") or 0) == 0:
        cursor.execute(f"ALTER TABLE {table_name} ADD {ddl}")


def ensure_wheel_prize_bonus_columns(cursor):
    """Add КБ prize columns to club_wheel_prizes for older installations."""
    global _wheel_prize_bonus_columns_ready
    if _wheel_prize_bonus_columns_ready:
        return

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'club_wheel_prizes'
          AND COLUMN_NAME IN ('bonus_amount', 'icon_emoji', 'token_amount')
        """)
    existing = {row.get("COLUMN_NAME") for row in cursor.fetchall()}
    if "bonus_amount" not in existing:
        cursor.execute("""
            ALTER TABLE club_wheel_prizes
            ADD COLUMN bonus_amount INT NOT NULL DEFAULT 0 AFTER image_url
            """)
    if "token_amount" not in existing:
        cursor.execute("""
            ALTER TABLE club_wheel_prizes
            ADD COLUMN token_amount INT NOT NULL DEFAULT 0 AFTER bonus_amount
            """)
    if "icon_emoji" not in existing:
        cursor.execute("""
            ALTER TABLE club_wheel_prizes
            ADD COLUMN icon_emoji VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL AFTER image_url
            """)
    else:
        cursor.execute("""
            ALTER TABLE club_wheel_prizes
            MODIFY icon_emoji VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL
            """)

    _wheel_prize_bonus_columns_ready = True


def ensure_wheel_settings_display_columns(cursor):
    """Add guest-facing display settings to wheel/cases configuration."""
    global _wheel_settings_display_columns_ready
    if _wheel_settings_display_columns_ready:
        return

    _ensure_column(
        cursor,
        "club_wheel_settings",
        "show_only_own_valuable_drops",
        "TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled",
    )
    _wheel_settings_display_columns_ready = True


def ensure_token_tables(cursor):
    """Create wheel token balance/ledger tables when they are missing.

    The SQL migration is also included in migrations/2026_05_01_wheel_tokens.sql,
    but this lazy guard keeps local/dev databases from crashing before the SQL is applied.
    """
    global _token_tables_ready
    if _token_tables_ready:
        return

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_wheel_token_balances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_wheel_token_balance (club_id, guest_id),
            KEY idx_guest_wheel_token_balance_guest (guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_wheel_token_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            balance_after INT NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_id VARCHAR(120) NULL,
            description VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_wheel_token_source (club_id, guest_id, source_type, source_id),
            KEY idx_guest_wheel_token_guest_created (club_id, guest_id, created_at),
            KEY idx_guest_wheel_token_source_type (source_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    _ensure_column(cursor, "guest_wheel_token_transactions", "expires_at", "DATETIME NULL AFTER description")
    _ensure_column(
        cursor,
        "guest_wheel_token_transactions",
        "expires_status",
        "VARCHAR(30) NOT NULL DEFAULT 'none' AFTER expires_at",
    )
    _ensure_column(cursor, "guest_wheel_token_transactions", "expired_at", "DATETIME NULL AFTER expires_status")
    _ensure_column(cursor, "guest_wheel_token_transactions", "expiration_transaction_id", "INT NULL AFTER expired_at")
    _ensure_index(
        cursor,
        "guest_wheel_token_transactions",
        "idx_guest_wheel_token_expiration",
        "KEY idx_guest_wheel_token_expiration (expires_status, expires_at)",
    )
    _token_tables_ready = True


def get_wheel_settings(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_settings_display_columns(cursor)
            cursor.execute(
                """
                SELECT
                    club_id,
                    tokens_start_date,
                    spin_cost,
                    is_enabled,
                    show_only_own_valuable_drops,
                    created_at,
                    updated_at
                FROM club_wheel_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_guest_profile_stats(guest_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(TIMESTAMPDIFF(MINUTE, date_start, date_stop)), 0) AS total_minutes
                FROM guest_sessions
                WHERE guest_id = %s
                  AND club_id = %s
                  AND date_start IS NOT NULL
                  AND date_stop IS NOT NULL
                """,
                (guest_id, club_id),
            )
            row = cursor.fetchone() or {}
            total_minutes = int(row.get("total_minutes") or 0)

        total_hours = total_minutes // 60

        return {
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "loyalty_level_placeholder": "—",
            "bonus_balance_placeholder": "—",
        }
    finally:
        conn.close()


def get_wheel_prizes(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                SELECT id,
                       club_id,
                       name,
                       description,
                       image_url,
                       icon_emoji,
                       bonus_amount,
                       token_amount,
                       probability,
                       is_active,
                       sort_order
                FROM club_wheel_prizes
                WHERE club_id = %s
                  AND is_active = 1
                ORDER BY sort_order, id
                """,
                (club_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_wheel_prizes_for_admin(club_id: int):
    """Все призы клуба для кабинета владельца (включая выключенные)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                SELECT id,
                       club_id,
                       name,
                       description,
                       image_url,
                       icon_emoji,
                       bonus_amount,
                       token_amount,
                       probability,
                       is_active,
                       sort_order
                FROM club_wheel_prizes
                WHERE club_id = %s
                ORDER BY sort_order, id
                """,
                (club_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def assert_active_wheel_probabilities_sum_is_100(club_id: int) -> None:
    """Сумма вероятностей активных призов должна быть 100% (допуск на погрешность float)."""
    row = {}
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(probability), 0) AS s
                FROM club_wheel_prizes
                WHERE club_id = %s
                  AND is_active = 1
                """,
                (club_id,),
            )
            row = cursor.fetchone() or {}
    finally:
        conn.close()
    n = int(row.get("n") or 0)
    s = float(row.get("s") or 0)
    if n <= 0:
        return
    if abs(s - 100.0) > 0.05:
        raise ValueError(
            f"Сумма вероятностей всех активных призов должна быть ровно 100% (сейчас {s:.2f}%). "
            "Подкорректируй веса призов."
        )


def _ensure_balance_row(cursor, guest_id: int, club_id: int):
    ensure_token_tables(cursor)
    cursor.execute(
        """
        INSERT IGNORE INTO guest_wheel_token_balances (club_id, guest_id, balance)
        VALUES (%s, %s, 0)
        """,
        (club_id, guest_id),
    )


def _get_balance_for_update(cursor, guest_id: int, club_id: int) -> int:
    _ensure_balance_row(cursor, guest_id, club_id)
    cursor.execute(
        """
        SELECT balance
        FROM guest_wheel_token_balances
        WHERE club_id = %s AND guest_id = %s
        FOR UPDATE
        """,
        (club_id, guest_id),
    )
    row = cursor.fetchone() or {}
    return int(row.get("balance") or 0)


def _transaction_exists(cursor, guest_id: int, club_id: int, source_type: str, source_id: str) -> bool:
    ensure_token_tables(cursor)
    cursor.execute(
        """
        SELECT id
        FROM guest_wheel_token_transactions
        WHERE club_id = %s
          AND guest_id = %s
          AND source_type = %s
          AND source_id = %s
        LIMIT 1
        """,
        (club_id, guest_id, source_type, source_id),
    )
    return bool(cursor.fetchone())


def _add_token_transaction(
    cursor,
    guest_id: int,
    club_id: int,
    amount: int,
    source_type: str,
    source_id: str,
    description: str | None = None,
    expires_at: datetime | None = None,
    expires_status: str | None = None,
) -> bool:
    """Add a token transaction once. Returns True when inserted, False when duplicate."""
    if amount == 0:
        return False

    source_id = str(source_id)
    if _transaction_exists(cursor, guest_id, club_id, source_type, source_id):
        return False

    balance = _get_balance_for_update(cursor, guest_id, club_id)
    balance_after = balance + int(amount)
    if balance_after < 0:
        raise ValueError("Недостаточно жетонов")

    cursor.execute(
        """
        UPDATE guest_wheel_token_balances
        SET balance = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE club_id = %s AND guest_id = %s
        """,
        (balance_after, club_id, guest_id),
    )
    cursor.execute(
        """
        INSERT INTO guest_wheel_token_transactions (
            club_id,
            guest_id,
            amount,
            balance_after,
            source_type,
            source_id,
            description,
            expires_at,
            expires_status,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            club_id,
            guest_id,
            int(amount),
            balance_after,
            source_type,
            source_id,
            description,
            expires_at,
            expires_status or ("active" if expires_at and amount > 0 else "none"),
            datetime.utcnow(),
        ),
    )
    return True


def add_guest_tokens(
    guest_id: int,
    club_id: int,
    amount: int,
    source_type: str = "manual",
    source_id: str | None = None,
    description: str | None = None,
):
    """Manual/test helper: creates a ledger row and changes balance.

    Use unique source_id values for idempotent operations; when source_id is omitted,
    a timestamp-based id is generated so the operation is always inserted.
    """
    source_id = source_id or f"manual:{datetime.utcnow().isoformat()}"
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            _add_token_transaction(cursor, guest_id, club_id, int(amount), source_type, source_id, description)
        conn.commit()
    finally:
        conn.close()


def award_first_authorization_token(guest_id: int, club_id: int, amount: int = 1) -> bool:
    """Give a one-time welcome wheel token after the guest's first successful bot authorization.

    Returns True only when the token was actually added. The unique transaction source
    protects the guest from repeated welcome credits on later logins.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            inserted = _add_token_transaction(
                cursor=cursor,
                guest_id=guest_id,
                club_id=club_id,
                amount=int(amount),
                source_type="first_authorization",
                source_id="welcome_token",
                description="Welcome-бонус за первую авторизацию в Cyber Bonus",
            )
        conn.commit()
        return bool(inserted)
    finally:
        conn.close()


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except Exception:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except Exception:
                return None
    return None


def _get_visit_days(cursor, guest_id: int, club_id: int, start_date) -> list[date]:
    cursor.execute(
        """
        SELECT DATE(date_start) AS visit_day
        FROM guest_sessions
        WHERE guest_id = %s
          AND club_id = %s
          AND date_start IS NOT NULL
          AND date_start >= %s
        GROUP BY DATE(date_start)
        ORDER BY visit_day
        """,
        (guest_id, club_id, start_date),
    )
    result = []
    for row in cursor.fetchall():
        visit_day = _to_date(row.get("visit_day"))
        if visit_day:
            result.append(visit_day)
    return result


def _calculate_streak_rows(visit_days: list[date]) -> list[dict]:
    rows = []
    cycle_start = None
    cycle_index = 0
    streak_day = 0

    for visit_day in visit_days:
        if cycle_start is None or visit_day >= cycle_start + timedelta(days=7):
            cycle_start = visit_day
            cycle_index += 1
            streak_day = 1
        else:
            streak_day += 1

        reward = min(streak_day, 7)
        cycle_end = cycle_start + timedelta(days=7)
        rows.append(
            {
                "visit_day": visit_day,
                "cycle_index": cycle_index,
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "streak_day": streak_day,
                "reward": reward,
            }
        )
    return rows


def get_guest_streak_info(guest_id: int, club_id: int):
    settings = get_wheel_settings(club_id)
    spin_cost = int((settings or {}).get("spin_cost") or 2)
    if spin_cost <= 0:
        spin_cost = 2

    empty = {
        "enabled": False,
        "spin_cost": spin_cost,
        "cycle_start": None,
        "cycle_end": None,
        "streak_days": 0,
        "current_reward": 0,
        "next_reward": 1,
        "days_left": None,
        "progress_percent": 0,
        "message": "Колесо фортуны пока не настроено.",
    }
    if not settings or not settings.get("is_enabled") or not settings.get("tokens_start_date"):
        return empty

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            rows = _calculate_streak_rows(_get_visit_days(cursor, guest_id, club_id, settings["tokens_start_date"]))
    finally:
        conn.close()

    today = datetime.utcnow().date()
    if not rows:
        return {
            **empty,
            "enabled": True,
            "next_reward": 1,
            "message": "Первое посещение принесёт 1 жетон.",
        }

    last = rows[-1]
    cycle_start = last["cycle_start"]
    cycle_end = last["cycle_end"]

    if today >= cycle_end:
        return {
            **empty,
            "enabled": True,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "streak_days": 0,
            "current_reward": 0,
            "next_reward": 1,
            "days_left": 0,
            "progress_percent": 0,
            "message": "Прошлый недельный цикл завершён. Следующий визит начнёт новый цикл и даст 1 жетон.",
        }

    current_cycle_rows = [row for row in rows if row["cycle_index"] == last["cycle_index"]]
    streak_days = len(current_cycle_rows)
    next_reward = min(streak_days + 1, 7)
    days_left = max((cycle_end - today).days, 0)

    return {
        "enabled": True,
        "spin_cost": spin_cost,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "streak_days": streak_days,
        "current_reward": last["reward"],
        "next_reward": next_reward,
        "days_left": days_left,
        "progress_percent": round(min(streak_days / 7, 1) * 100),
        "message": f"Следующее посещение до {cycle_end.strftime('%d.%m')} даст +{next_reward} жет.",
    }


def sync_guest_wheel_tokens(guest_id: int, club_id: int):
    """Synchronize streak wheel tokens and completed mission rewards.

    Mission rewards are intentionally independent from wheel settings: even if the wheel is disabled
    or tokens_start_date is not set, completed missions can still credit КБ.
    """
    settings = get_wheel_settings(club_id)

    if settings and settings.get("is_enabled") and settings.get("tokens_start_date"):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                ensure_token_tables(cursor)
                visit_days = _get_visit_days(cursor, guest_id, club_id, settings["tokens_start_date"])
                streak_rows = _calculate_streak_rows(visit_days)

                for row in streak_rows:
                    source_id = row["visit_day"].isoformat()
                    description = f"Недельная серия: день {row['streak_day']} из 7, +{row['reward']} жет."
                    _add_token_transaction(
                        cursor=cursor,
                        guest_id=guest_id,
                        club_id=club_id,
                        amount=row["reward"],
                        source_type="streak_visit",
                        source_id=source_id,
                        description=description,
                    )
            conn.commit()
        finally:
            conn.close()

    # Mission progress calculations use their own DB calls, so award mission rewards after streak sync.
    missions = get_guest_missions_with_progress(guest_id, club_id)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_token_tables(cursor)
            ensure_cm_bonus_tables(cursor)
            for mission in missions:
                if not mission.get("is_completed"):
                    continue

                token_reward = int(mission.get("token_reward") or 0)
                cm_bonus_reward = int(mission.get("cm_bonus_reward") or 0)
                mission_name = mission.get("name") or "задание"
                source_id = str(mission["id"])

                if token_reward > 0:
                    _add_token_transaction(
                        cursor=cursor,
                        guest_id=guest_id,
                        club_id=club_id,
                        amount=token_reward,
                        source_type="mission",
                        source_id=source_id,
                        description=f"Задание выполнено: {mission_name}",
                    )

                if cm_bonus_reward > 0:
                    add_cm_bonus_transaction(
                        cursor=cursor,
                        guest_id=guest_id,
                        club_id=club_id,
                        amount=cm_bonus_reward,
                        source_type="mission",
                        source_id=source_id,
                        description=f"Задание выполнено: {mission_name}",
                        status="done",
                    )
        conn.commit()
    finally:
        conn.close()

    return missions


def get_guest_tokens(guest_id: int, club_id: int, *, sync: bool = True):
    if sync:
        sync_guest_wheel_tokens(guest_id, club_id)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_token_tables(cursor)
            _ensure_balance_row(cursor, guest_id, club_id)
            cursor.execute(
                """
                SELECT balance
                FROM guest_wheel_token_balances
                WHERE club_id = %s AND guest_id = %s
                LIMIT 1
                """,
                (club_id, guest_id),
            )
            row = cursor.fetchone() or {}
            conn.commit()
            return max(int(row.get("balance") or 0), 0)
    finally:
        conn.close()


def get_guest_wheel_history(guest_id: int, club_id: int, limit: int = 8):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                SELECT
                    s.id AS spin_id,
                    s.created_at,
                    s.spent_tokens,
                    p.id AS prize_id,
                    p.name,
                    p.description,
                    p.image_url,
                    p.icon_emoji,
                    p.bonus_amount,
                    p.token_amount,
                    c.id AS claim_id,
                    c.status AS claim_status,
                    c.issued_at AS claim_issued_at,
                    c.cancelled_at AS claim_cancelled_at,
                    c.cancel_reason AS claim_cancel_reason
                FROM guest_wheel_spins s
                JOIN club_wheel_prizes p ON p.id = s.prize_id
                LEFT JOIN guest_prize_claims c ON c.spin_id = s.id
                WHERE s.guest_id = %s
                  AND s.club_id = %s
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT %s
                """,
                (guest_id, club_id, limit),
            )
            rows = cursor.fetchall()
            for row in rows:
                bonus_amount = int(row.get("bonus_amount") or 0)
                token_amount = int(row.get("token_amount") or 0)
                claim_status = row.get("claim_status")
                if bonus_amount > 0 or token_amount > 0:
                    row["prize_status_label"] = "начислено автоматически"
                elif claim_status == "issued":
                    row["prize_status_label"] = "выдан"
                elif claim_status == "cancelled":
                    row["prize_status_label"] = "отменён"
                elif claim_status in ("pending", "notified", "notify_failed"):
                    row["prize_status_label"] = "ожидает выдачи"
                else:
                    row["prize_status_label"] = "ожидает выдачи"
            return rows
    finally:
        conn.close()


def get_guest_token_history(guest_id: int, club_id: int, limit: int = 30):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_token_tables(cursor)
            cursor.execute(
                """
                SELECT id, amount, balance_after, source_type, source_id, description, created_at
                FROM guest_wheel_token_transactions
                WHERE club_id = %s AND guest_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (club_id, guest_id, limit),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def choose_wheel_prize(prizes):
    if not prizes:
        return None

    weighted_prizes = []
    total_weight = 0.0

    for prize in prizes:
        weight = float(prize.get("probability") or 0)
        if weight > 0:
            total_weight += weight
            weighted_prizes.append((prize, total_weight))

    if not weighted_prizes:
        return None

    rnd = random.uniform(0, total_weight)

    for prize, cumulative_weight in weighted_prizes:
        if rnd <= cumulative_weight:
            return prize

    return weighted_prizes[-1][0]


def save_guest_wheel_spin(
    guest_id: int,
    club_id: int,
    prize_id: int,
    spent_tokens: int = 2,
    *,
    test_mode: bool = False,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_token_tables(cursor)
            balance = _get_balance_for_update(cursor, guest_id, club_id)
            if balance < int(spent_tokens):
                raise ValueError("no_tokens")

            cursor.execute(
                """
                INSERT INTO guest_wheel_spins (
                    guest_id,
                    club_id,
                    prize_id,
                    spent_tokens,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (guest_id, club_id, prize_id, spent_tokens, datetime.utcnow()),
            )
            spin_id = cursor.lastrowid
            _add_token_transaction(
                cursor=cursor,
                guest_id=guest_id,
                club_id=club_id,
                amount=-int(spent_tokens),
                source_type="wheel_spin",
                source_id=str(spin_id),
                description="Прокрут колеса фортуны",
            )

            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                SELECT id, name, description, image_url, icon_emoji, bonus_amount, token_amount
                FROM club_wheel_prizes
                WHERE id = %s AND club_id = %s
                LIMIT 1
                """,
                (prize_id, club_id),
            )
            prize = cursor.fetchone()
            bonus_awarded = award_cm_bonuses_for_wheel_prize(
                cursor=cursor,
                guest_id=guest_id,
                club_id=club_id,
                spin_id=spin_id,
                prize=prize,
            )
            token_amount = int((prize or {}).get("token_amount") or 0)
            token_awarded = False
            if token_amount > 0:
                token_awarded = _add_token_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=token_amount,
                    source_type="wheel_prize",
                    source_id=str(spin_id),
                    description=f"Приз колеса: {(prize or {}).get('name') or 'приз'}",
                )
            claim_id = None
            if not bonus_awarded and not token_awarded:
                claim_id = create_prize_claim(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    spin_id=spin_id,
                    prize=prize,
                    test_mode=test_mode,
                )
        conn.commit()
    finally:
        conn.close()

    if claim_id:
        notify_prize_claim_admin_chat(claim_id)

    return spin_id


def serialize_wheel_prize(prize):
    """Public prize payload for guest UI/API.

    Probability and other internal fields must not be exposed to guests:
    the backend still uses full prize rows for weighted selection, while
    the frontend only receives data needed to render the wheel and result.
    """
    if not prize:
        return None

    return {
        "id": prize["id"],
        "name": prize.get("name"),
        "description": prize.get("description"),
        "image_url": prize.get("image_url"),
        "icon_emoji": prize.get("icon_emoji") or "🎁",
        "bonus_amount": int(prize.get("bonus_amount") or 0),
        "token_amount": int(prize.get("token_amount") or 0),
    }


def get_wheel_prize_by_id(prize_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                SELECT id,
                       club_id,
                       name,
                       description,
                       image_url,
                       icon_emoji,
                       bonus_amount,
                       token_amount,
                       probability,
                       is_active,
                       sort_order
                FROM club_wheel_prizes
                WHERE id = %s
                  AND club_id = %s
                LIMIT 1
                """,
                (prize_id, club_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_wheel_settings_for_admin(club_id: int):
    settings = get_wheel_settings(club_id)
    if settings:
        return settings

    return {
        "club_id": club_id,
        "tokens_start_date": None,
        "spin_cost": 2,
        "is_enabled": 0,
        "show_only_own_valuable_drops": 0,
    }


def save_wheel_settings(
    club_id: int,
    tokens_start_date,
    spin_cost: int,
    is_enabled: int,
    show_only_own_valuable_drops: int = 0,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_settings_display_columns(cursor)
            cursor.execute(
                """
                SELECT club_id
                FROM club_wheel_settings
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            exists = cursor.fetchone()

            if exists:
                cursor.execute(
                    """
                    UPDATE club_wheel_settings
                    SET tokens_start_date = %s,
                        spin_cost = %s,
                        is_enabled = %s,
                        show_only_own_valuable_drops = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE club_id = %s
                    """,
                    (tokens_start_date, spin_cost, is_enabled, show_only_own_valuable_drops, club_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO club_wheel_settings (
                        club_id,
                        tokens_start_date,
                        spin_cost,
                        is_enabled,
                        show_only_own_valuable_drops
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (club_id, tokens_start_date, spin_cost, is_enabled, show_only_own_valuable_drops),
                )

        conn.commit()
    finally:
        conn.close()


def create_wheel_prize(
    club_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    icon_emoji: str | None,
    bonus_amount: int,
    token_amount: int,
    probability: float,
    is_active: int = 1,
    sort_order: int = 0,
) -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                INSERT INTO club_wheel_prizes (
                    club_id,
                    name,
                    description,
                    image_url,
                    icon_emoji,
                    bonus_amount,
                    token_amount,
                    probability,
                    is_active,
                    sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    club_id,
                    name,
                    description,
                    image_url,
                    icon_emoji or "🎁",
                    int(bonus_amount or 0),
                    int(token_amount or 0),
                    probability,
                    is_active,
                    sort_order,
                ),
            )
            new_id = int(cursor.lastrowid)
        conn.commit()
        return new_id
    finally:
        conn.close()


def update_wheel_prize(
    prize_id: int,
    club_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    icon_emoji: str | None,
    bonus_amount: int,
    token_amount: int,
    probability: float,
    is_active: int = 1,
    sort_order: int = 0,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_wheel_prize_bonus_columns(cursor)
            cursor.execute(
                """
                UPDATE club_wheel_prizes
                SET name = %s,
                    description = %s,
                    image_url = %s,
                    icon_emoji = %s,
                    bonus_amount = %s,
                    token_amount = %s,
                    probability = %s,
                    is_active = %s,
                    sort_order = %s
                WHERE id = %s
                  AND club_id = %s
                """,
                (
                    name,
                    description,
                    image_url,
                    icon_emoji or "🎁",
                    int(bonus_amount or 0),
                    int(token_amount or 0),
                    probability,
                    is_active,
                    sort_order,
                    prize_id,
                    club_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def delete_wheel_prize(prize_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM club_wheel_prizes
                WHERE id = %s
                  AND club_id = %s
                """,
                (prize_id, club_id),
            )
        conn.commit()
    finally:
        conn.close()
