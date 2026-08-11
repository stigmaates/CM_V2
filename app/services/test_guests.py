from datetime import datetime

from app.core import get_db_connection
from app.services.wheel import ensure_token_tables


def ensure_test_guest(club_id: int, club_name: str | None) -> dict:
    guest_id = 900_000_000 + int(club_id)
    guest_name = f"Тестовый гость · {club_name or f'Клуб {club_id}'}"

    with get_db_connection() as db:
        with db.cursor() as cur:
            ensure_token_tables(cur)
            cur.execute(
                """
                INSERT INTO guests (guest_id, club_id, phone, fio, created_at, date_insert)
                VALUES (%s, %s, NULL, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    fio = VALUES(fio)
                """,
                (guest_id, club_id, guest_name, datetime.utcnow(), datetime.utcnow()),
            )
            cur.execute(
                """
                INSERT INTO guest_wheel_token_balances (club_id, guest_id, balance)
                VALUES (%s, %s, 100)
                ON DUPLICATE KEY UPDATE
                    balance = GREATEST(balance, VALUES(balance)),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (club_id, guest_id),
            )
        db.commit()

    return {"guest_id": guest_id, "club_id": club_id, "fio": guest_name}
