import random
from datetime import datetime, timedelta

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.prize_claims import (
    create_prize_claim,
    ensure_prize_claim_tables,
    get_prize_claim_by_spin_id,
    notify_prize_claim_admin_chat,
    serialize_prize_claim,
)
from app.services.wheel import (
    _add_token_transaction,
    _get_balance_for_update,
    ensure_token_tables,
)

_game_mode_column_ready = False
_case_tables_ready = False
VALUABLE_RARITIES = ("Редкий", "Очень редкий", "Ультра редкий")


def ensure_game_mode_column(cursor):
    """Add game_mode column to club_wheel_settings for older installations."""
    global _game_mode_column_ready
    if _game_mode_column_ready:
        return

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'club_wheel_settings'
          AND COLUMN_NAME = 'game_mode'
        """)
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE club_wheel_settings
            ADD COLUMN game_mode VARCHAR(10) NOT NULL DEFAULT 'wheel'
            """)

    _game_mode_column_ready = True


def ensure_case_tables(cursor):
    """Create cases-related tables when they are missing."""
    global _case_tables_ready
    if _case_tables_ready:
        return

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS club_cases (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT NULL,
            image_url TEXT NULL,
            badge_label VARCHAR(60) NULL,
            price_tokens INT NOT NULL DEFAULT 0,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            sort_order INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_club_cases_club (club_id, sort_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS club_case_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            case_id INT NOT NULL,
            club_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT NULL,
            image_url TEXT NULL,
            bonus_amount INT NOT NULL DEFAULT 0,
            token_amount INT NOT NULL DEFAULT 0,
            probability DECIMAL(8,4) NOT NULL DEFAULT 0,
            rarity_label VARCHAR(40) NOT NULL DEFAULT 'Обычный',
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            sort_order INT NOT NULL DEFAULT 0,
            KEY idx_case_items_case (case_id, sort_order),
            KEY idx_case_items_club (club_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'club_case_items'
          AND COLUMN_NAME = 'rarity_label'
        """)
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE club_case_items
            ADD COLUMN rarity_label VARCHAR(40) NOT NULL DEFAULT 'Обычный'
            AFTER probability
            """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_case_openings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            case_id INT NOT NULL,
            item_id INT NOT NULL,
            spent_tokens INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_case_openings_guest (club_id, guest_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    _case_tables_ready = True


# ---------------------------------------------------------------------------
# Game mode (wheel / cases)
# ---------------------------------------------------------------------------


def get_game_mode(club_id: int) -> str:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_game_mode_column(cursor)
            cursor.execute(
                "SELECT game_mode FROM club_wheel_settings WHERE club_id = %s LIMIT 1",
                (club_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    finally:
        conn.close()

    mode = (row or {}).get("game_mode") if row else None
    return mode if mode in ("wheel", "cases") else "wheel"


def save_game_mode(club_id: int, mode: str):
    if mode not in ("wheel", "cases"):
        raise ValueError("Некорректный режим: должен быть 'wheel' или 'cases'")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_game_mode_column(cursor)
            cursor.execute(
                "SELECT club_id FROM club_wheel_settings WHERE club_id = %s LIMIT 1",
                (club_id,),
            )
            exists = cursor.fetchone()

            if exists:
                cursor.execute(
                    "UPDATE club_wheel_settings SET game_mode = %s, updated_at = CURRENT_TIMESTAMP WHERE club_id = %s",
                    (mode, club_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO club_wheel_settings (club_id, tokens_start_date, spin_cost, is_enabled, game_mode)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (club_id, datetime.utcnow(), 2, 0, mode),
                )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cases CRUD
# ---------------------------------------------------------------------------

CASE_FIELDS = "id, club_id, name, description, image_url, badge_label, price_tokens, is_active, sort_order"


def get_cases_for_admin(club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                f"SELECT {CASE_FIELDS} FROM club_cases WHERE club_id = %s ORDER BY sort_order, id",
                (club_id,),
            )
            cases = cursor.fetchall()
            for case in cases:
                cursor.execute(
                    """
                    SELECT id, case_id, club_id, name, description, image_url,
                           bonus_amount, token_amount, probability, rarity_label, is_active, sort_order
                    FROM club_case_items
                    WHERE case_id = %s
                    ORDER BY sort_order, id
                    """,
                    (case["id"],),
                )
                case["items"] = cursor.fetchall()
        conn.commit()
        return cases
    finally:
        conn.close()


def get_cases(club_id: int):
    """Active cases with active items for guest UI."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                f"SELECT {CASE_FIELDS} FROM club_cases WHERE club_id = %s AND is_active = 1 ORDER BY sort_order, id",
                (club_id,),
            )
            cases = cursor.fetchall()
            for case in cases:
                cursor.execute(
                    """
                    SELECT id, case_id, club_id, name, description, image_url,
                           bonus_amount, token_amount, probability, rarity_label, is_active, sort_order
                    FROM club_case_items
                    WHERE case_id = %s AND is_active = 1
                    ORDER BY sort_order, id
                    """,
                    (case["id"],),
                )
                case["items"] = cursor.fetchall()
        conn.commit()
        return cases
    finally:
        conn.close()


def get_case_by_id(case_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                f"SELECT {CASE_FIELDS} FROM club_cases WHERE id = %s AND club_id = %s LIMIT 1",
                (case_id, club_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def _active_items_probability_sum(cursor, case_id: int) -> float:
    cursor.execute(
        "SELECT COALESCE(SUM(probability), 0) AS s FROM club_case_items WHERE case_id = %s AND is_active = 1",
        (case_id,),
    )
    row = cursor.fetchone() or {}
    return float(row.get("s") or 0)


def assert_case_active_items_probability_sum_is_100(case_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                "SELECT COUNT(*) AS n FROM club_case_items WHERE case_id = %s AND club_id = %s AND is_active = 1",
                (case_id, club_id),
            )
            n = int((cursor.fetchone() or {}).get("n") or 0)
            s = _active_items_probability_sum(cursor, case_id)
    finally:
        conn.close()

    if n <= 0:
        raise ValueError("У кейса нет активных предметов. Добавь хотя бы один предмет, чтобы включить кейс.")
    if abs(s - 100.0) > 0.05:
        raise ValueError(
            f"Сумма шансов активных предметов кейса должна быть ровно 100% (сейчас {s:.2f}%). "
            "Подкорректируй проценты выпадения."
        )


def create_case(
    club_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    badge_label: str | None,
    price_tokens: int,
    is_active: int = 1,
    sort_order: int = 0,
) -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                """
                INSERT INTO club_cases (club_id, name, description, image_url, badge_label, price_tokens, is_active, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (club_id, name, description, image_url, badge_label, int(price_tokens or 0), is_active, sort_order),
            )
            new_id = int(cursor.lastrowid)
        conn.commit()
        return new_id
    finally:
        conn.close()


def update_case(
    case_id: int,
    club_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    badge_label: str | None,
    price_tokens: int,
    is_active: int,
    sort_order: int,
):
    if is_active:
        assert_case_active_items_probability_sum_is_100(case_id, club_id)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                """
                UPDATE club_cases
                SET name = %s, description = %s, image_url = %s, badge_label = %s,
                    price_tokens = %s, is_active = %s, sort_order = %s
                WHERE id = %s AND club_id = %s
                """,
                (
                    name,
                    description,
                    image_url,
                    badge_label,
                    int(price_tokens or 0),
                    is_active,
                    sort_order,
                    case_id,
                    club_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def delete_case(case_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute("DELETE FROM club_case_items WHERE case_id = %s AND club_id = %s", (case_id, club_id))
            cursor.execute("DELETE FROM club_cases WHERE id = %s AND club_id = %s", (case_id, club_id))
        conn.commit()
    finally:
        conn.close()


def duplicate_case(case_id: int, club_id: int) -> int:
    """Copy a case with all items. The duplicate is disabled by default."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                f"SELECT {CASE_FIELDS} FROM club_cases WHERE id = %s AND club_id = %s LIMIT 1",
                (case_id, club_id),
            )
            source_case = cursor.fetchone()
            if not source_case:
                raise ValueError("Кейс не найден")

            cursor.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order
                FROM club_cases
                WHERE club_id = %s
                """,
                (club_id,),
            )
            sort_row = cursor.fetchone() or {}
            new_sort_order = int(sort_row.get("max_sort_order") or 0) + 1

            copy_name = f"{source_case.get('name') or 'Кейс'} (копия)"
            cursor.execute(
                """
                INSERT INTO club_cases (
                    club_id, name, description, image_url, badge_label,
                    price_tokens, is_active, sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
                """,
                (
                    club_id,
                    copy_name,
                    source_case.get("description"),
                    source_case.get("image_url"),
                    source_case.get("badge_label"),
                    int(source_case.get("price_tokens") or 0),
                    new_sort_order,
                ),
            )
            new_case_id = int(cursor.lastrowid)

            cursor.execute(
                """
                INSERT INTO club_case_items (
                    case_id, club_id, name, description, image_url,
                    bonus_amount, token_amount, probability, rarity_label,
                    is_active, sort_order
                )
                SELECT
                    %s, club_id, name, description, image_url,
                    bonus_amount, token_amount, probability, rarity_label,
                    is_active, sort_order
                FROM club_case_items
                WHERE case_id = %s
                  AND club_id = %s
                ORDER BY sort_order, id
                """,
                (new_case_id, case_id, club_id),
            )
        conn.commit()
        return new_case_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case items CRUD
# ---------------------------------------------------------------------------


def get_case_item_by_id(item_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                """
                SELECT id, case_id, club_id, name, description, image_url,
                       bonus_amount, token_amount, probability, rarity_label, is_active, sort_order
                FROM club_case_items
                WHERE id = %s AND club_id = %s
                LIMIT 1
                """,
                (item_id, club_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def create_case_item(
    case_id: int,
    club_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    bonus_amount: int,
    token_amount: int,
    probability: float,
    rarity_label: str = "Обычный",
    is_active: int = 1,
    sort_order: int = 0,
) -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                """
                INSERT INTO club_case_items (
                    case_id, club_id, name, description, image_url,
                    bonus_amount, token_amount, probability, rarity_label, is_active, sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    case_id,
                    club_id,
                    name,
                    description,
                    image_url,
                    int(bonus_amount or 0),
                    int(token_amount or 0),
                    probability,
                    rarity_label or "Обычный",
                    is_active,
                    sort_order,
                ),
            )
            new_id = int(cursor.lastrowid)
        conn.commit()
        return new_id
    finally:
        conn.close()


def update_case_item(
    item_id: int,
    club_id: int,
    case_id: int,
    name: str,
    description: str | None,
    image_url: str | None,
    bonus_amount: int,
    token_amount: int,
    probability: float,
    rarity_label: str,
    is_active: int,
    sort_order: int,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute(
                """
                UPDATE club_case_items
                SET name = %s, description = %s, image_url = %s,
                    bonus_amount = %s, token_amount = %s, probability = %s,
                    rarity_label = %s, is_active = %s, sort_order = %s
                WHERE id = %s AND club_id = %s AND case_id = %s
                """,
                (
                    name,
                    description,
                    image_url,
                    int(bonus_amount or 0),
                    int(token_amount or 0),
                    probability,
                    rarity_label or "Обычный",
                    is_active,
                    sort_order,
                    item_id,
                    club_id,
                    case_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def delete_case_item(item_id: int, club_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            cursor.execute("DELETE FROM club_case_items WHERE id = %s AND club_id = %s", (item_id, club_id))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Guest-facing: serialization, opening
# ---------------------------------------------------------------------------


def serialize_case_item(item):
    if not item:
        return None
    return {
        "id": item["id"],
        "name": item.get("name"),
        "description": item.get("description"),
        "image_url": item.get("image_url"),
        "bonus_amount": int(item.get("bonus_amount") or 0),
        "token_amount": int(item.get("token_amount") or 0),
        "probability": float(item.get("probability") or 0),
        "rarity_label": item.get("rarity_label") or "Обычный",
        "is_active": bool(item.get("is_active")),
        "sort_order": int(item.get("sort_order") or 0),
    }


def serialize_case(case):
    if not case:
        return None
    return {
        "id": case["id"],
        "name": case.get("name"),
        "description": case.get("description"),
        "image_url": case.get("image_url"),
        "badge_label": case.get("badge_label"),
        "price_tokens": int(case.get("price_tokens") or 0),
        "items": [serialize_case_item(i) for i in case.get("items") or []],
    }


def _looks_like_patronymic(value: str) -> bool:
    lower = (value or "").lower()
    return lower.endswith(("ич", "вна", "чна", "инична", "овна", "евна"))


def _looks_like_surname(value: str) -> bool:
    lower = (value or "").lower()
    return lower.endswith(
        ("ов", "ова", "ев", "ева", "ёв", "ёва", "ин", "ина", "ын", "ына", "ский", "ская", "цкий", "цкая")
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


def get_valuable_case_drops(limit: int = 24, days: int = 90, club_id: int | None = None):
    """Return recent valuable case drops for the guest-facing hype ticker."""
    safe_limit = max(1, min(int(limit or 24), 40))
    safe_days = max(1, min(int(days or 90), 365))
    since = datetime.utcnow() - timedelta(days=safe_days)
    club_filter = ""
    club_params: tuple[int, ...] = ()
    if club_id is not None:
        club_filter = "AND o.club_id = %s"
        club_params = (int(club_id),)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            ensure_prize_claim_tables(cursor)
            placeholders = ", ".join(["%s"] * len(VALUABLE_RARITIES))
            cursor.execute(
                f"""
                SELECT
                    o.id AS opening_id,
                    o.created_at,
                    g.fio AS guest_name,
                    c.name AS club_name,
                    cc.name AS case_name,
                    i.name AS item_name,
                    i.description AS item_description,
                    i.image_url AS item_image_url,
                    i.rarity_label
                FROM guest_case_openings o
                JOIN club_case_items i
                  ON i.id = o.item_id
                 AND i.club_id = o.club_id
                JOIN club_cases cc
                  ON cc.id = o.case_id
                 AND cc.club_id = o.club_id
                JOIN guests g
                  ON g.club_id = o.club_id
                 AND g.guest_id = o.guest_id
                JOIN clubs c
                  ON c.club_id = o.club_id
                LEFT JOIN guest_prize_claims pc
                  ON pc.spin_id = -o.id
                WHERE o.created_at >= %s
                  AND i.rarity_label IN ({placeholders})
                  {club_filter}
                  AND COALESCE(c.service_enabled, 1) = 1
                  AND COALESCE(g.fio, '') NOT LIKE 'Тестовый гость%%'
                  AND COALESCE(pc.prize_name, '') NOT LIKE '[ТЕСТ]%%'
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT %s
                """,
                (since, *VALUABLE_RARITIES, *club_params, safe_limit),
            )
            rows = cursor.fetchall() or []

        drops = []
        for row in rows:
            guest_first_name = _first_name(row.get("guest_name"))
            club_name = row.get("club_name") or "клуба"
            item_name = row.get("item_name") or "ценный приз"
            rarity = row.get("rarity_label") or "Очень редкий"
            created_at = row.get("created_at")
            drops.append(
                {
                    "opening_id": row.get("opening_id"),
                    "guest_name": guest_first_name,
                    "club_name": club_name,
                    "item_name": item_name,
                    "item_description": row.get("item_description") or "",
                    "case_name": row.get("case_name") or "Кейс",
                    "image_url": row.get("item_image_url"),
                    "rarity_label": rarity,
                    "headline": f"{guest_first_name} из {club_name}",
                    "tooltip": f"{guest_first_name} из {club_name} выиграл(а) «{item_name}»",
                    "created_at": created_at,
                    "created_at_label": created_at.strftime("%d.%m · %H:%M") if created_at else "",
                }
            )
        return drops
    finally:
        conn.close()


def choose_case_item(items):
    if not items:
        return None

    weighted = []
    total_weight = 0.0
    for item in items:
        weight = float(item.get("probability") or 0)
        if weight > 0:
            total_weight += weight
            weighted.append((item, total_weight))

    if not weighted:
        return None

    rnd = random.uniform(0, total_weight)
    for item, cumulative in weighted:
        if rnd <= cumulative:
            return item

    return weighted[-1][0]


def open_case(guest_id: int, club_id: int, case_id: int, *, test_mode: bool = False):
    conn = get_db_connection()
    claim_id = None
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            ensure_token_tables(cursor)
            ensure_cm_bonus_tables(cursor)
            ensure_prize_claim_tables(cursor)

            cursor.execute(
                f"SELECT {CASE_FIELDS} FROM club_cases WHERE id = %s AND club_id = %s AND is_active = 1 LIMIT 1",
                (case_id, club_id),
            )
            case = cursor.fetchone()
            if not case:
                raise ValueError("case_not_found")

            cursor.execute(
                """
                SELECT id, case_id, club_id, name, description, image_url,
                       bonus_amount, token_amount, probability, rarity_label, is_active, sort_order
                FROM club_case_items
                WHERE case_id = %s AND is_active = 1
                """,
                (case_id,),
            )
            items = cursor.fetchall()
            if not items:
                raise ValueError("no_items")

            price = int(case.get("price_tokens") or 0)
            if price > 0:
                balance = _get_balance_for_update(cursor, guest_id, club_id)
                if balance < price:
                    raise ValueError("no_tokens")

            item = choose_case_item(items)
            if not item:
                raise ValueError("invalid_items_config")

            cursor.execute(
                """
                INSERT INTO guest_case_openings (club_id, guest_id, case_id, item_id, spent_tokens, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (club_id, guest_id, case_id, item["id"], price, datetime.utcnow()),
            )
            opening_id = int(cursor.lastrowid)

            if price > 0:
                _add_token_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=-price,
                    source_type="case_open",
                    source_id=str(opening_id),
                    description=f"Открытие кейса: {case.get('name')}",
                )

            bonus_amount = int(item.get("bonus_amount") or 0)
            if bonus_amount > 0:
                add_cm_bonus_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=bonus_amount,
                    source_type="case_prize",
                    source_id=str(opening_id),
                    description=f"Приз кейса: {item.get('name') or 'приз'}",
                    status="done",
                )

            token_amount = int(item.get("token_amount") or 0)
            if token_amount > 0:
                _add_token_transaction(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    amount=token_amount,
                    source_type="case_prize",
                    source_id=str(opening_id),
                    description=f"Приз кейса: {item.get('name') or 'приз'}",
                )

            if bonus_amount <= 0 and token_amount <= 0:
                claim_id = create_prize_claim(
                    cursor=cursor,
                    guest_id=guest_id,
                    club_id=club_id,
                    spin_id=-opening_id,
                    prize={
                        "id": item["id"],
                        "name": item.get("name") or "Приз кейса",
                        "description": item.get("description"),
                        "image_url": item.get("image_url"),
                        "bonus_amount": 0,
                    },
                    test_mode=test_mode,
                )

        conn.commit()
    finally:
        conn.close()

    if claim_id:
        notify_prize_claim_admin_chat(claim_id)

    claim = get_prize_claim_by_spin_id(-opening_id)

    return {
        "opening_id": opening_id,
        "case": serialize_case(case),
        "item": serialize_case_item(item),
        "claim": serialize_prize_claim(claim),
    }


def get_guest_case_history(guest_id: int, club_id: int, limit: int = 8):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_case_tables(cursor)
            ensure_prize_claim_tables(cursor)
            cursor.execute(
                """
                SELECT
                    o.id AS opening_id,
                    o.created_at,
                    o.spent_tokens,
                    cs.id AS case_id,
                    cs.name AS case_name,
                    i.id AS item_id,
                    i.name,
                    i.description,
                    i.image_url,
                    i.bonus_amount,
                    i.token_amount,
                    c.id AS claim_id,
                    c.status AS claim_status,
                    c.issued_at AS claim_issued_at,
                    c.cancelled_at AS claim_cancelled_at,
                    c.cancel_reason AS claim_cancel_reason
                FROM guest_case_openings o
                JOIN club_case_items i ON i.id = o.item_id
                JOIN club_cases cs ON cs.id = o.case_id
                LEFT JOIN guest_prize_claims c ON c.spin_id = -o.id
                WHERE o.guest_id = %s AND o.club_id = %s
                ORDER BY o.created_at DESC, o.id DESC
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
                else:
                    row["prize_status_label"] = "ожидает выдачи"
            return rows
    finally:
        conn.close()
