from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection

AUTO_CODES = {
    "inactive_14_bonus": "Давно тебя не было",
    "streak_expiring_reminder": "Сгорающий стрик",
}


@dataclass
class Visit:
    club_id: int
    guest_id: int
    start: datetime
    stop: datetime | None

    @property
    def minutes(self) -> int | None:
        if not self.stop:
            return None
        return max(int((self.stop - self.start).total_seconds() // 60), 0)


def as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def as_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pct(part: int | float, total: int | float) -> str:
    if not total:
        return "0%"
    return f"{(float(part) / float(total) * 100):.1f}%"


def money(value: int | float) -> str:
    if abs(float(value) - round(float(value))) < 0.01:
        return f"{int(round(float(value))):,}".replace(",", " ")
    return f"{float(value):,.1f}".replace(",", " ")


def fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "-"


def fmt_days(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def normalize_phone(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    return digits


def fetch_all(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def table_columns(conn, table_name: str) -> set[str]:
    rows = fetch_all(
        conn,
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    return {str(row["COLUMN_NAME"]) for row in rows}


def fetch_sessions(
    conn, history_start: datetime, club_id: int | None
) -> tuple[dict[tuple[int, int], list[Visit]], dict[tuple[int, int], dict[str, Any]]]:
    params: list[Any] = [history_start]
    club_filter = ""
    if club_id is not None:
        club_filter = "AND gs.club_id = %s"
        params.append(club_id)

    rows = fetch_all(
        conn,
        f"""
        SELECT
            gs.club_id,
            gs.guest_id,
            gs.date_start,
            gs.date_stop,
            g.fio,
            g.phone,
            c.name AS club_name
        FROM guest_sessions gs
        LEFT JOIN guests g
          ON g.club_id = gs.club_id
         AND g.guest_id = gs.guest_id
        LEFT JOIN clubs c
          ON c.club_id = gs.club_id
        WHERE gs.date_start >= %s
          AND gs.guest_id IS NOT NULL
          {club_filter}
        ORDER BY gs.club_id, gs.guest_id, gs.date_start
        """,
        tuple(params),
    )

    raw: dict[tuple[int, int], list[Visit]] = defaultdict(list)
    guests: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        start = as_dt(row.get("date_start"))
        if not start:
            continue
        stop = as_dt(row.get("date_stop")) or start
        key = (int(row["club_id"]), int(row["guest_id"]))
        raw[key].append(Visit(key[0], key[1], start, stop))
        guests[key] = {
            "club_id": key[0],
            "guest_id": key[1],
            "club_name": row.get("club_name") or f"Клуб {key[0]}",
            "fio": row.get("fio") or f"Гость {key[1]}",
            "phone": row.get("phone") or "",
            "phone_norm": normalize_phone(row.get("phone")),
        }

    merged: dict[tuple[int, int], list[Visit]] = {}
    for key, visits in raw.items():
        result: list[Visit] = []
        for visit in sorted(visits, key=lambda item: item.start):
            if not result:
                result.append(visit)
                continue
            prev = result[-1]
            prev_stop = prev.stop or prev.start
            gap = visit.start - prev_stop
            if gap <= timedelta(hours=2):
                if not prev.stop or (visit.stop and visit.stop > prev.stop):
                    result[-1] = Visit(prev.club_id, prev.guest_id, prev.start, visit.stop)
            else:
                result.append(visit)
        merged[key] = result

    return merged, guests


def fetch_topups(conn, start: datetime, club_id: int | None) -> dict[tuple[int, int], list[dict[str, Any]]]:
    params: list[Any] = [start]
    club_filter = ""
    if club_id is not None:
        club_filter = "AND club_id = %s"
        params.append(club_id)

    rows = fetch_all(
        conn,
        f"""
        SELECT club_id, guest_id, amount, topup_at
        FROM guest_balance_topups
        WHERE topup_at >= %s
          AND guest_id IS NOT NULL
          {club_filter}
        """,
        tuple(params),
    )
    result: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[(int(row["club_id"]), int(row["guest_id"]))].append(row)
    return result


def topups_for_guest(
    topups_by_guest: dict[tuple[int, int], list[dict[str, Any]]],
    club_id: int,
    guest_id: int,
    start: datetime,
    end: datetime,
) -> float:
    total = 0.0
    for row in topups_by_guest.get((club_id, guest_id), []):
        dt = as_dt(row.get("topup_at"))
        if dt and start <= dt < end:
            total += as_float(row.get("amount"))
    return total


def nearest_visits(visits: list[Visit], at: datetime) -> tuple[Visit | None, Visit | None]:
    previous = None
    next_visit = None
    for visit in visits:
        if visit.start < at:
            previous = visit
        elif visit.start > at:
            next_visit = visit
            break
    return previous, next_visit


def count_visits(visits: list[Visit], start: datetime, end: datetime) -> int:
    return sum(1 for visit in visits if start <= visit.start < end)


def fetch_auto_events(conn, launch: datetime, club_id: int | None) -> list[dict[str, Any]]:
    columns = table_columns(conn, "auto_mailing_logs")
    code_parts = []
    if "automation_code" in columns:
        code_parts.append("aml.automation_code")
    if "auto_mailing_code" in columns:
        code_parts.append("aml.auto_mailing_code")
    raw_code_expr = (
        "COALESCE(" + ", ".join(code_parts) + ")" if len(code_parts) > 1 else (code_parts[0] if code_parts else "NULL")
    )
    code_expr = f"CAST(({raw_code_expr}) AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci"

    params: list[Any] = [launch]
    club_filter = ""
    if club_id is not None:
        club_filter = "AND aml.club_id = %s"
        params.append(club_id)

    return fetch_all(
        conn,
        f"""
        SELECT
            aml.id AS log_id,
            aml.club_id,
            aml.guest_id,
            {code_expr} AS code,
            aml.mailing_id,
            aml.created_at AS log_created_at,
            ams.title,
            ams.bonus_amount AS configured_bonus,
            m.created_at AS mailing_created_at,
            m.started_at AS mailing_started_at,
            mr.status AS delivery_status,
            mr.sent_at,
            g.fio,
            g.phone,
            c.name AS club_name,
            (
                SELECT COALESCE(SUM(cbt.amount), 0)
                FROM cm_bonus_transactions cbt
                WHERE cbt.club_id = aml.club_id
                  AND cbt.guest_id = aml.guest_id
                  AND cbt.amount > 0
                  AND cbt.source_type COLLATE utf8mb4_unicode_ci = _utf8mb4'auto_mailing' COLLATE utf8mb4_unicode_ci
                  AND (
                        cbt.source_id COLLATE utf8mb4_unicode_ci = CAST(aml.mailing_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci
                        OR cbt.created_at BETWEEN DATE_SUB(aml.created_at, INTERVAL 15 MINUTE)
                                          AND DATE_ADD(aml.created_at, INTERVAL 15 MINUTE)
                  )
            ) AS bonus_awarded
        FROM auto_mailing_logs aml
        LEFT JOIN auto_mailing_settings ams
          ON ams.club_id = aml.club_id
         AND ams.code COLLATE utf8mb4_unicode_ci = {code_expr}
        LEFT JOIN mailings m
          ON m.id = aml.mailing_id
         AND m.club_id = aml.club_id
        LEFT JOIN mailing_recipients mr
          ON mr.mailing_id = aml.mailing_id
         AND mr.guest_id = aml.guest_id
        LEFT JOIN guests g
          ON g.club_id = aml.club_id
         AND g.guest_id = aml.guest_id
        LEFT JOIN clubs c
          ON c.club_id = aml.club_id
        WHERE aml.created_at >= %s
          AND {code_expr} IN (
              _utf8mb4'inactive_14_bonus' COLLATE utf8mb4_unicode_ci,
              _utf8mb4'streak_expiring_reminder' COLLATE utf8mb4_unicode_ci
          )
          {club_filter}
        ORDER BY aml.created_at
        """,
        tuple(params),
    )


def fetch_wheel_rows(conn, launch: datetime, club_id: int | None) -> list[dict[str, Any]]:
    params: list[Any] = [launch]
    club_filter = ""
    if club_id is not None:
        club_filter = "AND s.club_id = %s"
        params.append(club_id)

    return fetch_all(
        conn,
        f"""
        SELECT
            s.club_id,
            s.guest_id,
            g.fio,
            g.phone,
            c.name AS club_name,
            COUNT(*) AS spins_count,
            COALESCE(SUM(p.bonus_amount), 0) AS prize_bonus_sum,
            COALESCE(SUM(s.spent_tokens), 0) AS spent_tokens,
            MIN(s.created_at) AS first_spin_at,
            MAX(s.created_at) AS last_spin_at
        FROM guest_wheel_spins s
        LEFT JOIN club_wheel_prizes p
          ON p.id = s.prize_id
         AND p.club_id = s.club_id
        LEFT JOIN guests g
          ON g.club_id = s.club_id
         AND g.guest_id = s.guest_id
        LEFT JOIN clubs c
          ON c.club_id = s.club_id
        WHERE s.created_at >= %s
          {club_filter}
        GROUP BY s.club_id, s.guest_id, g.fio, g.phone, c.name
        HAVING spins_count > 0
        ORDER BY spins_count DESC
        """,
        tuple(params),
    )


def fetch_wheel_prize_distribution(conn, launch: datetime, club_id: int | None) -> list[dict[str, Any]]:
    params: list[Any] = [launch]
    club_filter = ""
    if club_id is not None:
        club_filter = "AND s.club_id = %s"
        params.append(club_id)

    return fetch_all(
        conn,
        f"""
        SELECT
            s.club_id,
            c.name AS club_name,
            p.name AS prize_name,
            COUNT(*) AS hits,
            COALESCE(SUM(p.bonus_amount), 0) AS bonus_sum
        FROM guest_wheel_spins s
        LEFT JOIN club_wheel_prizes p
          ON p.id = s.prize_id
         AND p.club_id = s.club_id
        LEFT JOIN clubs c ON c.club_id = s.club_id
        WHERE s.created_at >= %s
          {club_filter}
        GROUP BY s.club_id, c.name, p.name
        ORDER BY s.club_id, hits DESC
        """,
        tuple(params),
    )


def build_period_stats(
    visits_by_guest: dict[tuple[int, int], list[Visit]], start: datetime, end: datetime
) -> dict[int, dict[str, Any]]:
    stats: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "days": max((end - start).days, 1),
            "active_guests": set(),
            "visits": 0,
            "return_20_events": 0,
            "return_20_guests": set(),
        }
    )
    for (club_id, guest_id), visits in visits_by_guest.items():
        previous = None
        for visit in visits:
            if visit.start >= end:
                break
            if visit.start < start:
                previous = visit
                continue
            stats[club_id]["active_guests"].add(guest_id)
            stats[club_id]["visits"] += 1
            if previous and (visit.start - previous.start).days >= 20:
                stats[club_id]["return_20_events"] += 1
                stats[club_id]["return_20_guests"].add(guest_id)
            previous = visit
    return stats


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_Нет данных по условиям._"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("\n", "<br>") for item in row) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find presentation-grade Cyber Bonus impact cases.")
    parser.add_argument("--club-id", type=int, help="Limit report to one internal club_id.")
    parser.add_argument("--launch-date", default="2026-06-05", help="Cyber Bonus launch date, YYYY-MM-DD.")
    parser.add_argument("--history-start", default="2026-03-01", help="Earliest sessions date to read, YYYY-MM-DD.")
    parser.add_argument("--top", type=int, default=8, help="Rows per examples block.")
    args = parser.parse_args()

    launch = datetime.fromisoformat(args.launch_date)
    now = datetime.now()
    after_days = max((now - launch).days, 1)
    before_start = launch - timedelta(days=after_days)
    history_start = min(datetime.fromisoformat(args.history_start), before_start - timedelta(days=60))

    conn = get_db_connection()
    try:
        visits_by_guest, guests = fetch_sessions(conn, history_start, args.club_id)
        topups_by_guest = fetch_topups(conn, before_start, args.club_id)
        auto_events = fetch_auto_events(conn, launch, args.club_id)
        wheel_rows = fetch_wheel_rows(conn, launch, args.club_id)
        prize_rows = fetch_wheel_prize_distribution(conn, launch, args.club_id)
    finally:
        conn.close()

    print("# Cyber Bonus: доказательные кейсы для презентации")
    print()
    print(f"Период после запуска: **{launch:%d.%m.%Y} - {now:%d.%m.%Y}**.")
    print(f"Сравнение идет с таким же периодом до запуска: **{before_start:%d.%m.%Y} - {launch:%d.%m.%Y}**.")
    print("Визит = цепочка Langame-сессий одного гостя, если пауза между сессиями не больше 2 часов.")
    print()

    pre_stats = build_period_stats(visits_by_guest, before_start, launch)
    post_stats = build_period_stats(visits_by_guest, launch, now)
    clubs = sorted(set(pre_stats) | set(post_stats))
    comparison_rows = []
    for club_id in clubs:
        pre = pre_stats.get(club_id, {})
        post = post_stats.get(club_id, {})
        club_name = next((g["club_name"] for key, g in guests.items() if key[0] == club_id), f"Клуб {club_id}")
        pre_active = len(pre.get("active_guests", set()))
        post_active = len(post.get("active_guests", set()))
        pre_visits = int(pre.get("visits", 0))
        post_visits = int(post.get("visits", 0))
        pre_return = len(pre.get("return_20_guests", set()))
        post_return = len(post.get("return_20_guests", set()))
        pre_freq = pre_visits / pre_active if pre_active else 0
        post_freq = post_visits / post_active if post_active else 0
        comparison_rows.append(
            [
                f"{club_id} · {club_name}",
                pre_active,
                post_active,
                pre_visits,
                post_visits,
                f"{pre_freq:.2f}",
                f"{post_freq:.2f}",
                pre_return,
                post_return,
                f"{(post_return / max(after_days, 1) * 30):.1f}/мес",
            ]
        )
    print("## Общая эффективность")
    print(
        markdown_table(
            [
                "Клуб",
                "Гостей до",
                "Гостей после",
                "Визитов до",
                "Визитов после",
                "Визитов/гость до",
                "Визитов/гость после",
                "20+ возвратов до",
                "20+ возвратов после",
                "20+ возвратов/мес после",
            ],
            comparison_rows,
        )
    )
    print()

    enriched_auto = []
    for row in auto_events:
        code = row.get("code")
        if code not in AUTO_CODES:
            continue
        at = (
            as_dt(row.get("sent_at"))
            or as_dt(row.get("mailing_started_at"))
            or as_dt(row.get("mailing_created_at"))
            or as_dt(row.get("log_created_at"))
        )
        if not at:
            continue
        key = (int(row["club_id"]), int(row["guest_id"]))
        previous, next_visit = nearest_visits(visits_by_guest.get(key, []), at)
        prev_gap_days = (at - previous.start).days if previous else None
        next_delay_hours = (next_visit.start - at).total_seconds() / 3600 if next_visit else None
        enriched_auto.append(
            {
                **row,
                "interaction_at": at,
                "previous_visit": previous,
                "next_visit": next_visit,
                "prev_gap_days": prev_gap_days,
                "next_delay_hours": next_delay_hours,
            }
        )

    inactive_candidates = [
        row
        for row in enriched_auto
        if row["code"] == "inactive_14_bonus"
        and row.get("prev_gap_days") is not None
        and row["prev_gap_days"] >= 20
        and row.get("next_delay_hours") is not None
        and row["next_delay_hours"] <= 14 * 24
    ]
    inactive_candidates.sort(key=lambda r: (-(r.get("prev_gap_days") or 0), r.get("next_delay_hours") or 99999))
    print("## Кейсы: вернулся после `давно тебя не было`")
    print(
        markdown_table(
            [
                "Клуб",
                "guest_id",
                "Гость",
                "Телефон",
                "Не был, дней",
                "Сообщение",
                "Бонус",
                "Следующий визит",
                "Задержка",
                "Длительность",
            ],
            [
                [
                    f"{r['club_id']} · {r.get('club_name') or '-'}",
                    r["guest_id"],
                    r.get("fio") or r["guest_id"],
                    r.get("phone") or "-",
                    r.get("prev_gap_days"),
                    fmt_dt(r.get("interaction_at")),
                    int(as_float(r.get("bonus_awarded")) or as_float(r.get("configured_bonus"))),
                    fmt_dt(r["next_visit"].start if r.get("next_visit") else None),
                    f"{(r['next_delay_hours'] / 24):.1f} дн.",
                    f"{r['next_visit'].minutes or '-'} мин" if r.get("next_visit") else "-",
                ]
                for r in inactive_candidates[: args.top]
            ],
        )
    )
    print()

    wheel_examples = []
    for row in wheel_rows:
        key = (int(row["club_id"]), int(row["guest_id"]))
        visits_after = count_visits(visits_by_guest.get(key, []), launch, now)
        topups_after = topups_for_guest(topups_by_guest, int(row["club_id"]), int(row["guest_id"]), launch, now)
        spins = int(row.get("spins_count") or 0)
        wheel_bonus = as_float(row.get("prize_bonus_sum"))
        bonus_per_spin = wheel_bonus / spins if spins else 0
        if spins >= 5:
            wheel_examples.append(
                {
                    **row,
                    "visits_after": visits_after,
                    "topups_after": topups_after,
                    "bonus_per_spin": bonus_per_spin,
                }
            )
    wheel_examples.sort(
        key=lambda r: (
            -as_float(r.get("spins_count")),
            as_float(r.get("bonus_per_spin")),
            -as_float(r.get("topups_after")),
        )
    )
    print("## Кейсы: много крутил рулетку, мало КБ, но много ходил")
    print(
        markdown_table(
            [
                "Клуб",
                "guest_id",
                "Гость",
                "Телефон",
                "Прокрутов",
                "КБ из рулетки",
                "КБ/прокрут",
                "Визитов после запуска",
                "Пополнения после запуска",
            ],
            [
                [
                    f"{r['club_id']} · {r.get('club_name') or '-'}",
                    r["guest_id"],
                    r.get("fio") or r["guest_id"],
                    r.get("phone") or "-",
                    int(r.get("spins_count") or 0),
                    money(as_float(r.get("prize_bonus_sum"))),
                    f"{as_float(r.get('bonus_per_spin')):.1f}",
                    r.get("visits_after"),
                    money(r.get("topups_after") or 0),
                ]
                for r in wheel_examples[: args.top]
            ],
        )
    )
    print()

    streak_candidates = [
        row
        for row in enriched_auto
        if row["code"] == "streak_expiring_reminder"
        and row.get("next_delay_hours") is not None
        and row["next_delay_hours"] <= 36
    ]
    streak_candidates.sort(key=lambda r: (r.get("next_delay_hours") or 99999, -(r.get("prev_gap_days") or 0)))
    print("## Кейсы: вернулся после напоминания о сгорающем стрике")
    print(
        markdown_table(
            [
                "Клуб",
                "guest_id",
                "Гость",
                "Телефон",
                "Предыдущий визит",
                "Сообщение",
                "Следующий визит",
                "Через часов",
                "Длительность",
            ],
            [
                [
                    f"{r['club_id']} · {r.get('club_name') or '-'}",
                    r["guest_id"],
                    r.get("fio") or r["guest_id"],
                    r.get("phone") or "-",
                    fmt_dt(r["previous_visit"].start if r.get("previous_visit") else None),
                    fmt_dt(r.get("interaction_at")),
                    fmt_dt(r["next_visit"].start if r.get("next_visit") else None),
                    f"{r['next_delay_hours']:.1f}",
                    f"{r['next_visit'].minutes or '-'} мин" if r.get("next_visit") else "-",
                ]
                for r in streak_candidates[: args.top]
            ],
        )
    )
    print()

    print("## Эффективность авторассылок")
    auto_summary_rows = []
    for code, title in AUTO_CODES.items():
        rows = [row for row in enriched_auto if row["code"] == code]
        delivered = [
            row
            for row in rows
            if str(row.get("delivery_status") or "").lower() in {"sent", "delivered", "completed", ""}
        ]
        returned_1d = [row for row in rows if row.get("next_delay_hours") is not None and row["next_delay_hours"] <= 24]
        returned_7d = [
            row for row in rows if row.get("next_delay_hours") is not None and row["next_delay_hours"] <= 7 * 24
        ]
        returned_14d = [
            row for row in rows if row.get("next_delay_hours") is not None and row["next_delay_hours"] <= 14 * 24
        ]
        auto_summary_rows.append(
            [
                title,
                len(rows),
                len(delivered),
                f"{len(returned_1d)} · {pct(len(returned_1d), len(rows))}",
                f"{len(returned_7d)} · {pct(len(returned_7d), len(rows))}",
                f"{len(returned_14d)} · {pct(len(returned_14d), len(rows))}",
            ]
        )
    print(
        markdown_table(
            [
                "Авторассылка",
                "Получателей",
                "Доставлено",
                "Вернулись за 1 день",
                "Вернулись за 7 дней",
                "Вернулись за 14 дней",
            ],
            auto_summary_rows,
        )
    )
    print()

    print("## Распределение призов рулетки")
    total_hits_by_club: dict[int, int] = defaultdict(int)
    for row in prize_rows:
        total_hits_by_club[int(row["club_id"])] += int(row.get("hits") or 0)
    prize_table = []
    for row in prize_rows[:30]:
        hits = int(row.get("hits") or 0)
        prize_table.append(
            [
                f"{row['club_id']} · {row.get('club_name') or '-'}",
                row.get("prize_name") or "Без названия",
                hits,
                pct(hits, total_hits_by_club[int(row["club_id"])]),
                money(as_float(row.get("bonus_sum"))),
            ]
        )
    print(markdown_table(["Клуб", "Приз", "Выпадений", "% от прокрутов клуба", "КБ выдано"], prize_table))
    print()

    total_spins = sum(int(row.get("spins_count") or 0) for row in wheel_rows)
    total_wheel_bonus = sum(as_float(row.get("prize_bonus_sum")) for row in wheel_rows)
    total_wheel_topups = sum(float(row.get("topups_after") or 0) for row in wheel_examples)
    print("## Инсайты для презентации")
    print(
        f"- После запуска зафиксировано **{total_spins}** прокрутов рулетки и выдано примерно **{money(total_wheel_bonus)} КБ** через призы рулетки."
    )
    if total_wheel_topups:
        print(
            f"- У гостей, активно крутивших рулетку, пополнения после запуска: **{money(total_wheel_topups)}**; это можно сопоставлять с выданными КБ как стоимостью удержания."
        )
    for code, title in AUTO_CODES.items():
        rows = [row for row in enriched_auto if row["code"] == code]
        returned_7d = [
            row for row in rows if row.get("next_delay_hours") is not None and row["next_delay_hours"] <= 7 * 24
        ]
        if rows:
            print(
                f"- `{title}`: **{pct(len(returned_7d), len(rows))}** получателей вернулись в течение 7 дней после сообщения."
            )


if __name__ == "__main__":
    main()
