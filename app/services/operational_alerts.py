from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core import get_db_connection
from app.services.backup_monitor import get_backup_status
from app.services.job_runs import ensure_background_job_runs_table, get_latest_job_runs_by_club

SYNC_JOB_TYPES = [
    "sync_guests_incremental",
    "sync_sessions_incremental",
    "sync_operations_incremental",
    "sync_balance_topups_incremental",
]

SYNC_JOB_LABELS = {
    "sync_guests_incremental": "Гости",
    "sync_sessions_incremental": "Сессии",
    "sync_operations_incremental": "Операции",
    "sync_balance_topups_incremental": "Пополнения",
}

SYNC_MAX_AGE_HOURS = {
    "sync_guests_incremental": 24,
    "sync_sessions_incremental": 8,
    "sync_operations_incremental": 8,
    "sync_balance_topups_incremental": 8,
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _age_minutes(dt: datetime | None, now: datetime) -> int | None:
    if not dt:
        return None
    return max(0, int((now - dt).total_seconds() // 60))


def _alert(
    severity: str,
    code: str,
    message: str,
    *,
    club_id: int | None = None,
    club_name: str | None = None,
    job_type: str | None = None,
    age_minutes: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "club_id": club_id,
        "club_name": club_name,
        "job_type": job_type,
        "age_minutes": age_minutes,
        "metadata": metadata or {},
    }


def build_operational_alerts(
    *,
    clubs: list[dict[str, Any]],
    latest_jobs_by_club: dict[int, dict[str, dict[str, Any]]],
    problem_jobs: list[dict[str, Any]],
    stuck_mailings: list[dict[str, Any]],
    backup_status: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or _utcnow()
    alerts: list[dict[str, Any]] = []

    for club in clubs:
        service_enabled = club.get("service_enabled", 1)
        if service_enabled is not None and int(service_enabled) == 0:
            continue

        club_id = int(club["club_id"])
        club_name = club.get("name")
        latest = latest_jobs_by_club.get(club_id, {})
        for job_type in SYNC_JOB_TYPES:
            row = latest.get(job_type)
            label = SYNC_JOB_LABELS[job_type]
            max_age_hours = SYNC_MAX_AGE_HOURS[job_type]

            if not row:
                alerts.append(
                    _alert(
                        "warning",
                        "sync_missing",
                        f"{label}: нет данных о последнем запуске",
                        club_id=club_id,
                        club_name=club_name,
                        job_type=job_type,
                    )
                )
                continue

            status = row.get("status")
            started_at = row.get("started_at")
            age_minutes = _age_minutes(started_at, now)
            if status in {"error", "stale"}:
                alerts.append(
                    _alert(
                        "error",
                        f"sync_{status}",
                        f"{label}: последний запуск завершился статусом {status}",
                        club_id=club_id,
                        club_name=club_name,
                        job_type=job_type,
                        age_minutes=age_minutes,
                        metadata={"error_text": row.get("error_text")},
                    )
                )
            elif age_minutes is not None and age_minutes > max_age_hours * 60:
                alerts.append(
                    _alert(
                        "warning",
                        "sync_stale",
                        f"{label}: данные не обновлялись больше {max_age_hours} ч",
                        club_id=club_id,
                        club_name=club_name,
                        job_type=job_type,
                        age_minutes=age_minutes,
                    )
                )

    for row in problem_jobs:
        alerts.append(
            _alert(
                "error",
                "background_job_failed",
                f"{row.get('job_type')}: статус {row.get('status')}",
                club_id=row.get("club_id"),
                job_type=row.get("job_type"),
                age_minutes=_age_minutes(row.get("started_at"), now),
                metadata={
                    "job_run_id": row.get("id"),
                    "status": row.get("status"),
                    "error_text": row.get("error_text"),
                },
            )
        )

    for row in stuck_mailings:
        alerts.append(
            _alert(
                "error",
                "mailing_stuck",
                f"Рассылка #{row.get('id')} зависла в статусе {row.get('status')}",
                club_id=row.get("club_id"),
                age_minutes=_age_minutes(row.get("activity_at"), now),
                metadata={
                    "mailing_id": row.get("id"),
                    "status": row.get("status"),
                    "recipients_count": row.get("recipients_count"),
                },
            )
        )

    if backup_status and backup_status.get("status") in {"error", "warning"}:
        latest = backup_status.get("latest") or {}
        alerts.append(
            _alert(
                backup_status["status"],
                "backup_stale" if latest else "backup_missing",
                backup_status.get("message") or "Backup требует внимания",
                age_minutes=(
                    int(backup_status["age_hours"]) * 60 if backup_status.get("age_hours") is not None else None
                ),
                metadata={
                    "latest_backup": latest.get("name"),
                    "latest_backup_path": latest.get("path"),
                    "configured_dirs": backup_status.get("configured_dirs") or [],
                    "max_age_hours": backup_status.get("max_age_hours"),
                },
            )
        )

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda item: (severity_rank.get(item["severity"], 9), item.get("club_id") or 0, item["code"]))
    return alerts


def _fetch_clubs(cursor) -> list[dict[str, Any]]:
    try:
        cursor.execute("""
            SELECT club_id, name, service_enabled
            FROM clubs
            ORDER BY club_id
            """)
    except Exception:
        cursor.execute("SELECT club_id, name, 1 AS service_enabled FROM clubs ORDER BY club_id")
    return cursor.fetchall() or []


def _fetch_problem_jobs(cursor, *, limit: int) -> list[dict[str, Any]]:
    ensure_background_job_runs_table(cursor)
    base_query = """
        SELECT r.id, r.job_type, r.club_id, r.status, r.started_at, r.error_text
        FROM background_job_runs r
        INNER JOIN (
            SELECT club_id, job_type, MAX(started_at) AS latest_started_at
            FROM background_job_runs
            WHERE club_id IS NOT NULL
            GROUP BY club_id, job_type
        ) latest
          ON latest.club_id = r.club_id
         AND latest.job_type = r.job_type
         AND latest.latest_started_at = r.started_at
        WHERE r.status IN ('error', 'stale')
        ORDER BY r.started_at DESC
        LIMIT %s
    """
    active_query = base_query.replace(
        "FROM background_job_runs r\n        INNER JOIN",
        "FROM background_job_runs r\n        LEFT JOIN clubs c ON c.club_id = r.club_id\n        INNER JOIN",
        1,
    ).replace(
        "WHERE r.status IN ('error', 'stale')",
        "WHERE r.status IN ('error', 'stale')\n          AND COALESCE(c.service_enabled, 1) = 1",
        1,
    )
    try:
        cursor.execute(active_query, (limit,))
    except Exception:
        cursor.execute(base_query, (limit,))

    return cursor.fetchall() or []


def _fetch_stuck_mailings(cursor, *, max_age_minutes: int) -> list[dict[str, Any]]:
    cutoff = _utcnow() - timedelta(minutes=max_age_minutes)
    try:
        cursor.execute(
            """
            SELECT id, club_id, status, recipients_count,
                   COALESCE(started_at, created_at) AS activity_at
            FROM mailings
            WHERE status IN ('queued', 'in_progress')
              AND COALESCE(started_at, created_at) < %s
            ORDER BY COALESCE(started_at, created_at) ASC
            LIMIT 20
            """,
            (cutoff,),
        )
        return cursor.fetchall() or []
    except Exception:
        return []


def get_operational_alerts(
    *,
    problem_job_limit: int = 20,
    stuck_mailing_minutes: int = 60,
) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            clubs = _fetch_clubs(cursor)
            problem_jobs = _fetch_problem_jobs(cursor, limit=problem_job_limit)
            stuck_mailings = _fetch_stuck_mailings(cursor, max_age_minutes=stuck_mailing_minutes)

        latest_jobs_by_club = get_latest_job_runs_by_club(SYNC_JOB_TYPES)
        return build_operational_alerts(
            clubs=clubs,
            latest_jobs_by_club=latest_jobs_by_club,
            problem_jobs=problem_jobs,
            stuck_mailings=stuck_mailings,
            backup_status=get_backup_status(),
        )
    finally:
        conn.close()


def summarize_alerts(alerts: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"error": 0, "warning": 0, "info": 0, "total": len(alerts)}
    for alert in alerts:
        severity = alert.get("severity") or "info"
        if severity not in summary:
            summary[severity] = 0
        summary[severity] += 1
    return summary
