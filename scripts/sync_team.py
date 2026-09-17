"""Read-only Langame staff/shift import and module-registration reconstruction."""

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.core import get_db_connection
from app.services.guest_pulse import rows


def parse_time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def fetch(client, path, **params):
    response = client.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    if body.get("status") is not True or not isinstance(body.get("data"), list):
        raise ValueError("unexpected_api_response")
    return body


def fetch_team(client, secret, configured_id=None):
    clubs = fetch(client, "clubs/list")["data"]
    matches = [c for c in clubs if str(c.get("club_secret")) == secret]
    if configured_id:
        matches = [c for c in clubs if int(c["id"]) == configured_id]
    elif not matches and len(clubs) == 1:
        matches = clubs
    if len(matches) != 1:
        raise ValueError("langame_club_mapping_required")
    external_id = int(matches[0]["id"])
    users = fetch(client, "users/list")["data"]
    shifts, page = [], 1
    while True:
        body = fetch(client, "working_shifts/list", page=page, page_limit=100)
        shifts.extend(s for s in body["data"] if int(s.get("list_clubs_id") or 0) == external_id)
        pages = int(body.get("total_pages", 1))
        if page >= pages:
            break
        page += 1
        if page > 10000:
            raise ValueError("shift_pagination_limit")
    # Preserve former staff referenced by historical shifts.
    ids = {int(s["user_id"]) for s in shifts}
    users = [u for u in users if str(u.get("work_point")) == str(external_id) or int(u["id"]) in ids]
    return external_id, users, shifts


def reconstruct_registrations(conn, club_id):
    candidates = rows(
        conn,
        """SELECT guest_id, MIN(at) AS registered_at FROM (
        SELECT guest_id,created_at AS at FROM guest_wheel_token_transactions
          WHERE club_id=%s AND source_type='first_authorization'
        UNION ALL SELECT guest_id,created_at FROM cm_bonus_transactions
          WHERE club_id=%s AND source_type='first_authorization' AND status='done'
        UNION ALL SELECT guest_id,created_at FROM guest_login_tokens
          WHERE club_id=%s AND is_confirmed=1 AND guest_id IS NOT NULL
        UNION ALL SELECT guest_id,reviewed_at FROM guest_telegram_link_requests
          WHERE club_id=%s AND status='approved'
        ) evidence WHERE at IS NOT NULL AND guest_id IS NOT NULL GROUP BY guest_id""",
        (club_id,) * 4,
    )
    with conn.cursor() as cur:
        for row in candidates:
            cur.execute(
                """INSERT INTO module_registrations
                (club_id,guest_id,registered_at,source,is_estimated,observed_at)
                VALUES(%s,%s,%s,'reconstructed',1,UTC_TIMESTAMP())
                ON DUPLICATE KEY UPDATE
                registered_at=IF(is_estimated=1 AND (registered_at IS NULL OR VALUES(registered_at)<registered_at),VALUES(registered_at),registered_at),
                source=IF(is_estimated=1,'reconstructed',source)""",
                (club_id, row["guest_id"], row["registered_at"]),
            )
        cur.execute(
            """INSERT IGNORE INTO module_registrations
            (club_id,guest_id,registered_at,source,is_estimated,observed_at)
            SELECT club_id,guest_id,NULL,'unknown',1,UTC_TIMESTAMP() FROM guests
            WHERE club_id=%s AND telegram_id IS NOT NULL AND telegram_id<>0""",
            (club_id,),
        )
    conn.commit()


def sync_club(conn, club, *, external_id=None):
    secret = str(club["secret"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", secret):
        raise ValueError("invalid_club_host")
    previous = rows(conn, "SELECT langame_club_id FROM team_sync_state WHERE club_id=%s", (club["club_id"],))
    external_id = external_id or (previous[0]["langame_club_id"] if previous else None)
    with httpx.Client(
        base_url=f"https://{secret}.langame.ru/public_api/",
        headers={"X-API-KEY": club["lg_api_key"].strip(), "Accept": "application/json"},
        timeout=60,
        transport=httpx.HTTPTransport(retries=2),
    ) as client:
        external_id, users, shifts = fetch_team(client, secret, external_id)
    # Fetch every page successfully before replacing cached team data.
    conn.rollback()
    conn.begin()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM team_admins WHERE club_id=%s", (club["club_id"],))
            cur.execute("DELETE FROM team_shifts WHERE club_id=%s", (club["club_id"],))
            for u in users:
                cur.execute(
                    "INSERT INTO team_admins VALUES(%s,%s,%s,%s,%s)",
                    (
                        club["club_id"],
                        int(u["id"]),
                        u.get("username") or u.get("email") or f"Администратор #{u['id']}",
                        str(u.get("admin_status") or ""),
                        u.get("work_schedule"),
                    ),
                )
            for s in shifts:
                start, stop = parse_time(s.get("date_start")), parse_time(s.get("date_stop"))
                if start is None or (stop is not None and stop < start):
                    raise ValueError("invalid_shift_dates")
                cur.execute(
                    "INSERT INTO team_shifts VALUES(%s,%s,%s,%s,%s)",
                    (club["club_id"], int(s["id"]), int(s["user_id"]), start, stop),
                )
            cur.execute(
                """INSERT INTO team_sync_state VALUES(%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP(),NULL)
                ON DUPLICATE KEY UPDATE langame_club_id=VALUES(langame_club_id),updated_at=VALUES(updated_at),
                attempted_at=VALUES(attempted_at),error_code=NULL""",
                (club["club_id"], external_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"Team club {club['club_id']}: admins={len(users)}, shifts={len(shifts)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--club-id", type=int)
    parser.add_argument("--langame-club-id", type=int)
    args = parser.parse_args()
    if args.langame_club_id and not args.club_id:
        raise ValueError("--langame-club-id requires --club-id")
    conn = get_db_connection()
    failed = False
    acquired = False
    try:
        acquired = bool(
            rows(conn, "SELECT GET_LOCK(CONCAT('team-sync:',MD5(DATABASE())),0) AS acquired")[0]["acquired"]
        )
        if not acquired:
            print("Team sync already running; skipped.", flush=True)
            return 0
        clubs = rows(
            conn,
            "SELECT club_id,secret,lg_api_key FROM clubs WHERE service_enabled=1"
            + (" AND club_id=%s" if args.club_id else ""),
            (args.club_id,) if args.club_id else (),
        )
        for club in clubs:
            try:
                reconstruct_registrations(conn, club["club_id"])
                sync_club(conn, club, external_id=args.langame_club_id)
            except Exception as exc:
                conn.rollback()
                code = (
                    f"HTTP_{exc.response.status_code}"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else str(exc)
                    if isinstance(exc, ValueError)
                    and str(exc)
                    in (
                        "langame_club_mapping_required",
                        "invalid_shift_dates",
                        "invalid_club_host",
                        "unexpected_api_response",
                        "shift_pagination_limit",
                    )
                    else type(exc).__name__
                )
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO team_sync_state(club_id,attempted_at,error_code) VALUES(%s,UTC_TIMESTAMP(),%s)
                        ON DUPLICATE KEY UPDATE attempted_at=VALUES(attempted_at),error_code=VALUES(error_code)""",
                        (club["club_id"], code),
                    )
                conn.commit()
                print(f"Team club {club['club_id']}: {code}", flush=True)
                failed = True
    finally:
        if acquired:
            rows(conn, "SELECT RELEASE_LOCK(CONCAT('team-sync:',MD5(DATABASE())))")
        conn.close()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
