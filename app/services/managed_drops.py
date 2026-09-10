from datetime import UTC, datetime
from uuid import UUID

from pymysql.err import IntegrityError

from app.core import get_db_connection
from app.services.reception import PHONE_NORMALIZED_SQL, _phone_variants
from app.services.timezones import utc_datetime_to_club_local

STATUS_LABELS = {
    "pending": "Ожидает открытия",
    "consumed": "Приз выпал",
    "cancelled": "Отменено",
    "invalid": "Приз недоступен",
}


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def find_drop_guests(cursor, club_id, phone):
    variants = _phone_variants(phone)
    if not variants:
        return []
    placeholders = ", ".join(["%s"] * len(variants))
    cursor.execute(
        f"""SELECT guest_id, fio, phone FROM guests
            WHERE club_id = %s AND {PHONE_NORMALIZED_SQL} IN ({placeholders})
            ORDER BY guest_id DESC LIMIT 50""",
        (club_id, *variants),
    )
    return cursor.fetchall()


def _catalog(cursor, club_id):
    cursor.execute(
        """SELECT c.id AS target_id, c.name AS target_name, i.id AS prize_id, i.name AS prize_name
           FROM club_cases c JOIN club_case_items i ON i.case_id = c.id AND i.club_id = c.club_id
           WHERE c.club_id = %s AND c.is_active = 1 AND i.is_active = 1
           ORDER BY c.sort_order, c.id, i.sort_order, i.id""",
        (club_id,),
    )
    targets = {}
    for row in cursor.fetchall():
        key = f"case:{row['target_id']}"
        target = targets.setdefault(key, {"key": key, "name": row["target_name"], "prizes": []})
        target["prizes"].append({"id": row["prize_id"], "name": row["prize_name"]})
    cursor.execute(
        """SELECT p.id, p.name FROM club_wheel_prizes p
           JOIN club_wheel_settings s ON s.club_id = p.club_id
           WHERE p.club_id = %s AND p.is_active = 1 AND s.is_enabled = 1
           ORDER BY p.sort_order, p.id""",
        (club_id,),
    )
    prizes = cursor.fetchall()
    if prizes:
        targets["wheel:0"] = {"key": "wheel:0", "name": "Колесо фортуны", "prizes": prizes}
    return list(targets.values())


def get_managed_drop_page(club_id, phone="", *, show_all=False, page=1, timezone_name=None):
    limit = 50 if show_all else 5
    page = max(int(page), 1) if show_all else 1
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            guests = find_drop_guests(cursor, club_id, phone) if phone else []
            targets = _catalog(cursor, club_id)
            cursor.execute("SELECT COUNT(*) AS cnt FROM managed_drops WHERE club_id = %s", (club_id,))
            total = int((cursor.fetchone() or {}).get("cnt") or 0)
            pages = max((total + limit - 1) // limit, 1)
            page = min(page, pages)
            cursor.execute(
                "SELECT * FROM managed_drops WHERE club_id = %s ORDER BY id DESC LIMIT %s OFFSET %s",
                (club_id, limit, (page - 1) * limit),
            )
            history = cursor.fetchall()
        for row in history:
            row["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
            for field in ("created_at", "finished_at"):
                value = utc_datetime_to_club_local(row.get(field), timezone_name)
                row[field + "_label"] = value.strftime("%d.%m.%Y %H:%M") if value else "—"
        return {
            "guests": guests,
            "targets": targets,
            "history": history,
            "total": total,
            "page": page,
            "pages": pages,
            "show_all": show_all,
        }
    finally:
        conn.close()


def create_managed_drop(*, club_id, guest_id, phone, target, prize_id, actor_user_id, actor_name, request_key):
    try:
        request_key = str(UUID(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Обновите страницу и повторите назначение") from None
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Re-submitting a form after consumption must not arm a second prize.
            cursor.execute(
                "SELECT id FROM managed_drops WHERE club_id = %s AND request_key = %s", (club_id, request_key)
            )
            existing = cursor.fetchone()
            if existing:
                return int(existing["id"])
            guest = next((g for g in find_drop_guests(cursor, club_id, phone) if int(g["guest_id"]) == guest_id), None)
            if not guest:
                raise ValueError("Выберите гостя из результатов поиска в текущем клубе")
            selected = next((t for t in _catalog(cursor, club_id) if t["key"] == target), None)
            prize = next((p for p in (selected or {}).get("prizes", []) if int(p["id"]) == prize_id), None)
            if not prize:
                raise ValueError("Кейс, колесо или приз недоступны. Обновите страницу")
            kind, target_id = target.split(":")
            cursor.execute(
                """INSERT INTO managed_drops
                   (club_id, guest_id, kind, target_id, prize_id, guest_name, guest_phone,
                    target_name, prize_name, actor_user_id, actor_name, request_key, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    club_id,
                    guest_id,
                    kind,
                    int(target_id),
                    prize_id,
                    guest.get("fio"),
                    guest.get("phone"),
                    selected["name"],
                    prize["name"],
                    actor_user_id,
                    actor_name,
                    request_key,
                    _now(),
                ),
            )
            drop_id = int(cursor.lastrowid)
        conn.commit()
        return drop_id
    except IntegrityError:
        conn.rollback()
        raise ValueError(
            "Для этого гостя уже есть назначение в выбранном кейсе или колесе. Сначала отмените его"
        ) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_managed_drop(club_id, drop_id, actor_user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE managed_drops SET status = 'cancelled', finished_at = %s, cancelled_by = %s
                   WHERE id = %s AND club_id = %s AND status = 'pending'""",
                (_now(), actor_user_id, drop_id, club_id),
            )
            changed = cursor.rowcount > 0
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reserve_managed_drop(cursor, *, club_id, guest_id, kind, target_id, prizes, test_mode=False):
    """Lock the one-shot record within the opening transaction; never commit here."""
    if test_mode:
        return None, None
    cursor.execute(
        """SELECT id, prize_id FROM managed_drops
           WHERE club_id = %s AND guest_id = %s AND kind = %s AND target_id = %s AND status = 'pending'
           LIMIT 1 FOR UPDATE""",
        (club_id, guest_id, kind, target_id),
    )
    drop = cursor.fetchone()
    if not drop:
        return None, None
    prize = next((p for p in prizes if int(p["id"]) == int(drop["prize_id"])), None)
    if prize is None:
        cursor.execute(
            """UPDATE managed_drops SET status = 'invalid', finished_at = %s, reason = %s
               WHERE id = %s AND status = 'pending'""",
            (_now(), "Приз удалён или отключён до открытия", drop["id"]),
        )
        return None, None
    return int(drop["id"]), prize


def consume_managed_drop(cursor, drop_id, opening_id):
    if drop_id is None:
        return
    cursor.execute(
        """UPDATE managed_drops SET status = 'consumed', finished_at = %s, opening_id = %s
           WHERE id = %s AND status = 'pending'""",
        (_now(), opening_id, drop_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("Managed drop reservation was lost")
