import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv

load_dotenv()

from app.core import get_db_connection
from app.services.cm_bonuses import add_cm_bonus_transaction, ensure_cm_bonus_tables
from app.services.job_locks import job_lock
from app.services.job_runs import finish_job_run, start_job_run


def _guest_visited_after_grant(cursor, grant: dict) -> bool:
    cursor.execute(
        """
        SELECT id
        FROM guest_sessions
        WHERE club_id = %s
          AND guest_id = %s
          AND date_start >= %s
          AND date_start <= %s
        LIMIT 1
        """,
        (
            grant["club_id"],
            grant["guest_id"],
            grant["created_at"],
            grant["expires_at"],
        ),
    )
    return bool(cursor.fetchone())


def _current_bonus_balance(cursor, club_id: int, guest_id: int) -> int:
    cursor.execute(
        """
        SELECT balance
        FROM cm_bonus_balances
        WHERE club_id = %s AND guest_id = %s
        FOR UPDATE
        """,
        (club_id, guest_id),
    )
    row = cursor.fetchone() or {}
    return int(row.get("balance") or 0)


def process_expiring_bonuses(limit: int = 500) -> dict:
    conn = get_db_connection()
    job_id = None
    try:
        with conn.cursor() as cur:
            ensure_cm_bonus_tables(cur)
        conn.commit()

        with job_lock("process_expiring_bonuses", club_id=0, ttl_minutes=10) as lock:
            if not lock.acquired:
                return {"status": "skipped", "reason": "lock_active", "expired": 0, "kept": 0}

            job_id = start_job_run("process_expiring_bonuses", club_id=0)
            expired = 0
            kept = 0

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        club_id,
                        guest_id,
                        amount,
                        created_at,
                        expires_at,
                        description,
                        expires_status
                    FROM cm_bonus_transactions
                    WHERE amount > 0
                      AND expires_status = 'active'
                      AND expires_at IS NOT NULL
                      AND expires_at <= NOW()
                    ORDER BY expires_at ASC, id ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                grants = cur.fetchall()

            for grant in grants:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id,
                            club_id,
                            guest_id,
                            amount,
                            created_at,
                            expires_at,
                            description,
                            expires_status
                        FROM cm_bonus_transactions
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (grant["id"],),
                    )
                    locked_grant = cur.fetchone()
                    if not locked_grant or locked_grant.get("expires_status") != "active":
                        conn.commit()
                        continue

                    if _guest_visited_after_grant(cur, locked_grant):
                        cur.execute(
                            """
                            UPDATE cm_bonus_transactions
                        SET expires_status = 'kept',
                                expired_at = NOW()
                            WHERE id = %s
                            """,
                            (locked_grant["id"],),
                        )
                        kept += 1
                        conn.commit()
                        continue

                    balance = _current_bonus_balance(cur, int(locked_grant["club_id"]), int(locked_grant["guest_id"]))
                    burn_amount = min(int(locked_grant["amount"] or 0), balance)
                    expiration_transaction_id = None
                    if burn_amount > 0:
                        added = add_cm_bonus_transaction(
                            cursor=cur,
                            guest_id=int(locked_grant["guest_id"]),
                            club_id=int(locked_grant["club_id"]),
                            amount=-burn_amount,
                            source_type="bonus_expiration",
                            source_id=str(locked_grant["id"]),
                            description=f"Сгорел бонус #{locked_grant['id']}",
                            status="done",
                        )
                        if added:
                            expiration_transaction_id = cur.lastrowid

                    cur.execute(
                        """
                        UPDATE cm_bonus_transactions
                        SET expires_status = 'expired',
                            expired_at = NOW(),
                            expiration_transaction_id = %s
                        WHERE id = %s
                        """,
                        (expiration_transaction_id, locked_grant["id"]),
                    )
                    expired += 1
                    conn.commit()

            finish_job_run(
                job_id,
                "success",
                rows_received=len(grants),
                rows_saved=expired,
                metadata={"expired": expired, "kept": kept},
            )
            return {"status": "success", "expired": expired, "kept": kept}
    except Exception as exc:
        conn.rollback()
        if job_id:
            finish_job_run(job_id, "error", error_text=str(exc))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    result = process_expiring_bonuses()
    print(result)
