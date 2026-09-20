"""Account links are serialized per club, including ordinary contact-based login."""

from app.core import get_db_connection

HELP_MESSAGE = "Обратитесь к администратору для помощи с этой проблемой"


def find_linked_guest(club_id, telegram_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT guest_id, club_id, fio, phone, telegram_id FROM guests "
                "WHERE club_id = %s AND telegram_id = %s LIMIT 2",
                (club_id, telegram_id),
            )
            rows = cur.fetchall()
            if len(rows) > 1:
                raise ValueError(HELP_MESSAGE)
            return rows[0] if rows else None
    finally:
        conn.close()


def _lock_club(cur, club_id):
    cur.execute("SELECT club_id FROM clubs WHERE club_id = %s FOR UPDATE", (club_id,))
    if not cur.fetchone():
        raise ValueError(HELP_MESSAGE)


def _check_link(cur, club_id, guest_id, telegram_id):
    cur.execute(
        "SELECT guest_id, telegram_id, phone FROM guests WHERE club_id = %s AND guest_id = %s FOR UPDATE",
        (club_id, guest_id),
    )
    guest = cur.fetchone()
    if not guest or (guest.get("telegram_id") and int(guest["telegram_id"]) != int(telegram_id)):
        raise ValueError("Аккаунт уже связан с другим Telegram или недоступен. " + HELP_MESSAGE)
    cur.execute(
        "SELECT guest_id FROM guests WHERE club_id = %s AND telegram_id = %s AND guest_id <> %s LIMIT 1",
        (club_id, telegram_id, guest_id),
    )
    if cur.fetchone():
        raise ValueError("Этот Telegram уже связан с другим гостем клуба. " + HELP_MESSAGE)
    return guest


def bind_verified_contact(guest_id, club_id, telegram_id, expected_phone=None):
    conn = get_db_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            _lock_club(cur, club_id)
            guest = _check_link(cur, club_id, guest_id, telegram_id)
            if expected_phone is not None and guest.get("phone") != expected_phone:
                raise ValueError("Номер гостя изменился. Повторите вход.")
            cur.execute(
                "UPDATE guests SET telegram_id = %s WHERE club_id = %s AND guest_id = %s",
                (telegram_id, club_id, guest_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_link_request(club_id, guest_id, telegram_id, telegram_phone, lg_phone, admin_chat_id):
    conn = get_db_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            _lock_club(cur, club_id)
            guest = _check_link(cur, club_id, guest_id, telegram_id)
            if guest.get("telegram_id"):
                raise ValueError("Привязка уже существует. Откройте новую ссылку входа на сайте.")
            if guest["phone"] != lg_phone:
                raise ValueError("Данные гостя изменились. Повторите поиск.")
            cur.execute(
                "SELECT id FROM guest_telegram_link_requests WHERE club_id = %s AND telegram_id = %s "
                "AND status = 'pending' AND created_at > UTC_TIMESTAMP() - INTERVAL 24 HOUR LIMIT 1",
                (club_id, telegram_id),
            )
            if cur.fetchone():
                raise ValueError("Ваша заявка уже ожидает проверки администратора.")
            cur.execute(
                "SELECT COUNT(*) AS n FROM guest_telegram_link_requests WHERE club_id = %s "
                "AND telegram_id = %s AND created_at > UTC_TIMESTAMP() - INTERVAL 24 HOUR",
                (club_id, telegram_id),
            )
            if cur.fetchone()["n"] >= 3:
                raise ValueError("Слишком много заявок. " + HELP_MESSAGE)
            cur.execute(
                "INSERT INTO guest_telegram_link_requests "
                "(club_id, guest_id, telegram_id, telegram_phone, lg_phone, admin_chat_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())",
                (club_id, guest_id, telegram_id, telegram_phone, lg_phone, str(admin_chat_id)),
            )
            request_id = cur.lastrowid
        conn.commit()
        return request_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_notification_failed(request_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE guest_telegram_link_requests SET status = 'send_failed' WHERE id = %s AND status = 'pending'",
                (request_id,),
            )
        conn.commit()
    finally:
        conn.close()


def review_link_request(request_id, chat_id, reviewer_id, approve):
    conn = get_db_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT club_id FROM guest_telegram_link_requests WHERE id = %s", (request_id,))
            ref = cur.fetchone()
            if not ref:
                raise ValueError("Заявка не найдена")
            _lock_club(cur, ref["club_id"])
            cur.execute(
                "SELECT *, created_at <= UTC_TIMESTAMP() - INTERVAL 24 HOUR AS expired "
                "FROM guest_telegram_link_requests WHERE id = %s FOR UPDATE",
                (request_id,),
            )
            row = cur.fetchone()
            cur.execute("SELECT cm_bonus_admin_chat_id FROM clubs WHERE club_id = %s FOR UPDATE", (row["club_id"],))
            configured_chat = str((cur.fetchone() or {}).get("cm_bonus_admin_chat_id") or "").strip()
            if str(chat_id) != row["admin_chat_id"] or configured_chat != str(chat_id):
                raise ValueError("Подтвердить заявку можно только в текущем чате этого клуба")
            if row["status"] != "pending":
                raise ValueError("Заявка уже обработана")
            if row["expired"]:
                raise ValueError("Заявка устарела. Гостю нужно отправить новую.")
            if approve:
                guest = _check_link(cur, row["club_id"], row["guest_id"], row["telegram_id"])
                if guest["phone"] != row["lg_phone"]:
                    raise ValueError("Номер LG изменился. Гостю нужно отправить новую заявку.")
                cur.execute(
                    "UPDATE guests SET telegram_id = %s WHERE club_id = %s AND guest_id = %s",
                    (row["telegram_id"], row["club_id"], row["guest_id"]),
                )
            cur.execute(
                "UPDATE guest_telegram_link_requests SET status = %s, reviewed_by = %s, "
                "reviewed_at = UTC_TIMESTAMP() WHERE id = %s",
                ("approved" if approve else "rejected", reviewer_id, request_id),
            )
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
