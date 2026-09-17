"""Club-scoped Guest Pulse persistence and replay. No reward or mailing side effects."""

import json
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from app.config import BALANCE_TOPUP_MAX_AMOUNT
from app.services.guest_pulse_scores import (
    add_history,
    audience,
    engagement,
    health,
    lifecycle,
    value_scores,
    visit_features,
)
from app.services.timezones import club_local_datetime_to_utc, utc_datetime_to_club_local
from app.services.visits import collapse_sessions_to_visits


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=lambda v: v.isoformat(), allow_nan=False)


def loads(value):
    return json.loads(value) if isinstance(value, str) else value


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def load_sources(conn, club_id, timezone_name):
    guests = rows(conn, "SELECT guest_id, fio, phone, telegram_id FROM guests WHERE club_id=%s", (club_id,))
    sessions = rows(
        conn,
        """SELECT guest_id,date_start,date_stop FROM guest_sessions WHERE club_id=%s
        AND guest_id IS NOT NULL AND date_start IS NOT NULL AND date_stop>date_start ORDER BY guest_id,date_start""",
        (club_id,),
    )
    topups = rows(
        conn,
        """SELECT guest_id,amount,topup_at FROM guest_balance_topups
        WHERE club_id=%s AND guest_id IS NOT NULL AND amount>0 AND amount<=%s""",
        (club_id, BALANCE_TOPUP_MAX_AMOUNT),
    )
    activity = []
    sources = (
        ("guest_mission_completions", "completed_at", "mission", "1=1"),
        ("guest_wheel_token_transactions", "created_at", "authorization", "source_type='first_authorization'"),
        ("cm_bonus_transactions", "created_at", "authorization", "source_type='first_authorization' AND status='done'"),
        ("guest_case_openings", "created_at", "case", "1=1"),
        ("guest_wheel_spins", "created_at", "wheel", "1=1"),
        (
            "guest_game_contracts",
            "started_at",
            "contract_selected",
            "status IN ('active','completed','expired')",
        ),
        (
            "guest_game_contracts",
            "completed_at",
            "contract_completed",
            "status='completed' AND completed_at IS NOT NULL",
        ),
        (
            "cm_bonus_redeem_requests",
            "processed_at",
            "conversion",
            "status='credited' AND processed_at IS NOT NULL",
        ),
        (
            "cm_bonus_transactions",
            "created_at",
            "code",
            "source_type IN ('system_code','promo_code') AND status='done'",
        ),
        ("guest_prize_claims", "issued_at", "reward", "status='issued' AND issued_at IS NOT NULL"),
    )
    for table, field, kind, where in sources:
        for row in rows(
            conn,
            f"SELECT guest_id,{field} AS at FROM {table} WHERE club_id=%s AND guest_id IS NOT NULL AND {where}",
            (club_id,),
        ):
            row["kind"] = kind
            row["at"] = utc_datetime_to_club_local(row["at"], timezone_name)
            activity.append(row)
    grouped = {key: defaultdict(list) for key in ("sessions", "topups", "events")}
    for row in sessions:
        row["date_start"] = utc_datetime_to_club_local(row["date_start"], timezone_name)
        row["date_stop"] = utc_datetime_to_club_local(row["date_stop"], timezone_name)
        grouped["sessions"][int(row["guest_id"])].append(row)
    for row in topups:
        row["topup_at"] = utc_datetime_to_club_local(row["topup_at"], timezone_name)
        grouped["topups"][int(row["guest_id"])].append(row)
    for row in activity:
        grouped["events"][int(row["guest_id"])].append(row)
    return guests, grouped


def calculate_club(sources, now, previous=None, historical=False):
    guests, grouped = sources
    previous = previous or {}
    result = []
    for guest in guests:
        gid = int(guest["guest_id"])
        # Filter before grouping so future sessions cannot leak into old snapshots.
        visits = collapse_sessions_to_visits([s for s in grouped["sessions"][gid] if s["date_stop"] <= now])
        f = visit_features(visits, now)
        if not f["visits_total"]:
            continue
        topups = [
            float(t["amount"]) for t in grouped["topups"][gid] if now - timedelta(days=90) <= t["topup_at"] <= now
        ]
        f.update(
            guest_id=gid, revenue_90d=sum(topups), avg_check_90d=sum(topups) / f["visits_90d"] if f["visits_90d"] else 0
        )
        h = health(f)
        events = grouped["events"][gid]
        known_authorization = min((event["at"] for event in events), default=None)
        connected = (
            bool(known_authorization and known_authorization <= now) if historical else bool(guest.get("telegram_id"))
        )
        # User-approved approximation: binding persists after its first surviving evidence.
        # Authorization is evidence for Telegram, not a game action or a daily streak.
        e = engagement([event for event in events if event["kind"] != "authorization"], connected, now)
        e["estimated"] = historical
        state = lifecycle(f, h, now, previous.get(gid))
        if state["lifecycle_status"] == "REACTIVATED":
            h["reason_codes"] = ["RETURNED_AFTER_CHURN", *h["reason_codes"]]
            h["reason_code"] = "RETURNED_AFTER_CHURN"
            h["reason_text"] = "Вернулся после длительного отсутствия или высокого риска."
        result.append(
            {
                "guest_id": gid,
                "name": guest.get("fio") or f"Гость #{gid}",
                "phone": guest.get("phone"),
                **state,
                "health": h,
                "engagement": e,
                "visits": f,
                "history_note": (
                    "Восстановлено по событиям. Вовлечённость приблизительная: Telegram считается подключённым с первой сохранённой авторизации или активности."
                    if historical
                    else None
                ),
            }
        )
    value = value_scores([r["visits"] for r in result])
    for row in result:
        row["value"] = {
            **value[row["guest_id"]],
            **{k: row["visits"][k] for k in ("revenue_90d", "played_hours_90d", "visits_90d", "avg_check_90d")},
        }
        row["audience_type"] = audience(row)
    return result


def previous_states(current):
    result = {}
    for row in current:
        r = dict(row)
        for field in ("last_visit_date", "lifecycle_status_changed_at", "reactivated_at"):
            if isinstance(r.get(field), str):
                r[field] = datetime.fromisoformat(r[field])
        result[int(r["guest_id"])] = r
    return result


def write_events(cur, club_id, values, old, timezone_name, reconstructed=False):
    params = []
    for row in values:
        before = old.get(row["guest_id"], {})
        if before.get("lifecycle_status") == row["lifecycle_status"]:
            continue
        params.append(
            (
                club_id,
                row["guest_id"],
                before.get("lifecycle_status"),
                row["lifecycle_status"],
                club_local_datetime_to_utc(row["lifecycle_status_changed_at"], timezone_name),
                before.get("health", {}).get("score"),
                row["health"]["score"],
                row["health"]["reason_code"],
                int(reconstructed),
            )
        )
    if params:
        cur.executemany(
            """INSERT INTO guest_lifecycle_events
            (club_id,guest_id,from_status,to_status,changed_at,health_before,health_after,reason_code,reconstructed)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=id""",
            params,
        )


def write_snapshot(cur, club_id, values, day, now_utc, reconstructed=False):
    if values:
        cur.executemany(
            """INSERT INTO guest_score_history
            (club_id,guest_id,snapshot_date,health_score,value_score,engagement_score,lifecycle_status,detail_json,reconstructed,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE snapshot_date=snapshot_date""",
            [
                (
                    club_id,
                    r["guest_id"],
                    day,
                    r["health"]["score"],
                    r["value"]["score"],
                    r["engagement"]["score"],
                    r["lifecycle_status"],
                    dumps(r),
                    int(reconstructed),
                    now_utc,
                )
                for r in values
            ],
        )


def refresh_club(conn, club_id, *, now_utc=None, backfill=False, force=False):
    now_utc = now_utc or datetime.now(UTC).replace(tzinfo=None)
    lock_name = f"guest-pulse:{club_id}"
    if not rows(conn, "SELECT GET_LOCK(CONCAT(MD5(DATABASE()),%s),0) AS acquired", (lock_name,))[0]["acquired"]:
        return {"club_id": club_id, "status": "locked"}
    try:
        conn.commit()
        club = rows(conn, "SELECT timezone FROM clubs WHERE club_id=%s AND service_enabled=1", (club_id,))
        if not club:
            return {"club_id": club_id, "status": "disabled"}
        tz = club[0].get("timezone")
        now = utc_datetime_to_club_local(now_utc, tz)
        state = (rows(conn, "SELECT * FROM guest_pulse_clubs WHERE club_id=%s", (club_id,)) or [{}])[0]
        dirty = (rows(conn, "SELECT generation FROM guest_pulse_dirty WHERE club_id=%s", (club_id,)) or [{}])[0].get(
            "generation"
        )
        daily_due = now.hour >= 4 and state.get("snapshot_date") != now.date()
        needs_backfill = backfill or not state.get("backfilled_at")
        # A daily recency refresh is mandatory even when sources did not change.
        if not force and not dirty and not daily_due and not needs_backfill:
            return {"club_id": club_id, "status": "unchanged"}
        sources = load_sources(conn, club_id, tz)
        old = previous_states(
            [
                loads(r["detail_json"])
                for r in rows(conn, "SELECT detail_json FROM guest_pulse_current WHERE club_id=%s", (club_id,))
            ]
        )
        with conn.cursor() as cur:
            if needs_backfill:
                replay = {}
                # Warm-up captures prior risk and the 14-day reactivation window.
                for days in range(45, 0, -1):
                    at = datetime.combine(now.date() - timedelta(days=days), time(4))
                    values = calculate_club(sources, at, replay, historical=True)
                    if days <= 30:
                        write_snapshot(cur, club_id, values, at.date(), now_utc, True)
                        # Do not add reconstructed transitions after a live timeline has begun.
                        if not state.get("backfilled_at"):
                            write_events(cur, club_id, values, replay, tz, True)
                    replay = previous_states(values)
                if not old:
                    old = replay
            values = calculate_club(sources, now, old)
            write_events(cur, club_id, values, old, tz)
            if daily_due:
                write_snapshot(cur, club_id, values, now.date(), now_utc)
        history = defaultdict(list)
        for r in rows(
            conn,
            """SELECT guest_id,snapshot_date,health_score,value_score,engagement_score,reconstructed FROM guest_score_history
                WHERE club_id=%s AND snapshot_date>=%s AND snapshot_date<%s""",
            (club_id, now.date() - timedelta(days=30), now.date()),
        ):
            for key in ("health_score", "value_score", "engagement_score"):
                r[key] = float(r[key]) if r[key] is not None else None
            history[int(r["guest_id"])].append(r)
        for r in values:
            add_history(r, history[r["guest_id"]], now.date())
        with conn.cursor() as cur:
            # Atomic replacement; readers see either the old or the new club cohort.
            cur.execute("DELETE FROM guest_pulse_current WHERE club_id=%s", (club_id,))
            if values:
                cur.executemany(
                    """INSERT INTO guest_pulse_current
                    (club_id,guest_id,health_score,value_score,engagement_score,lifecycle_status,audience_type,detail_json,calculated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        (
                            club_id,
                            r["guest_id"],
                            r["health"]["score"],
                            r["value"]["score"],
                            r["engagement"]["score"],
                            r["lifecycle_status"],
                            r["audience_type"],
                            dumps(r),
                            now_utc,
                        )
                        for r in values
                    ],
                )
            cur.execute(
                """UPDATE user_portrait up LEFT JOIN guest_pulse_current p ON p.club_id=up.club_id AND p.guest_id=up.guest_id
                SET up.health_score=p.health_score, up.value_score=p.value_score, up.engagement_score=p.engagement_score,
                    up.lifecycle_status=p.lifecycle_status, up.pulse_updated_at=p.calculated_at,
                    up.health_delta_14d=CASE WHEN JSON_TYPE(JSON_EXTRACT(p.detail_json,'$.health.delta_14d'))='NULL' THEN NULL
                        ELSE JSON_UNQUOTE(JSON_EXTRACT(p.detail_json,'$.health.delta_14d')) END
                WHERE up.club_id=%s""",
                (club_id,),
            )
            cur.execute(
                """INSERT INTO guest_pulse_clubs (club_id,calculated_at,snapshot_date,backfilled_at,guest_count)
                VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE calculated_at=VALUES(calculated_at),
                    snapshot_date=VALUES(snapshot_date),backfilled_at=VALUES(backfilled_at),guest_count=VALUES(guest_count)""",
                (
                    club_id,
                    now_utc,
                    now.date() if daily_due else state.get("snapshot_date"),
                    now_utc if needs_backfill else state.get("backfilled_at"),
                    len(values),
                ),
            )
            if dirty is not None:
                cur.execute("DELETE FROM guest_pulse_dirty WHERE club_id=%s AND generation=%s", (club_id, dirty))
        conn.commit()
        return {"club_id": club_id, "status": "updated", "guests": len(values)}
    except Exception:
        conn.rollback()
        raise
    finally:
        # A committed source update during the refresh increments generation and survives.
        rows(conn, "SELECT RELEASE_LOCK(CONCAT(MD5(DATABASE()),%s)) AS released", (lock_name,))
        conn.commit()


def get_current(conn, club_id):
    return [
        {**loads(r["detail_json"]), "has_telegram": bool(r["telegram_id"])}
        for r in rows(
            conn,
            """SELECT p.detail_json,g.telegram_id FROM guest_pulse_current p
        JOIN guests g ON g.club_id=p.club_id AND g.guest_id=p.guest_id WHERE p.club_id=%s ORDER BY p.guest_id""",
            (club_id,),
        )
    ]
