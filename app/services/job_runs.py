from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from app.core import get_db_connection


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_background_job_runs_table(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS background_job_runs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            job_type VARCHAR(80) NOT NULL,
            club_id INT NULL,
            status VARCHAR(30) NOT NULL,
            started_at DATETIME NOT NULL,
            finished_at DATETIME NULL,
            duration_ms INT NULL,
            rows_received INT NULL,
            rows_saved INT NULL,
            error_text TEXT NULL,
            metadata_json JSON NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_background_job_runs_club_type_started (club_id, job_type, started_at),
            KEY idx_background_job_runs_status_started (status, started_at),
            KEY idx_background_job_runs_started (started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def start_job_run(
    job_type: str,
    *,
    club_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            ensure_background_job_runs_table(cursor)
            cursor.execute(
                """
                INSERT INTO background_job_runs (
                    job_type, club_id, status, started_at, metadata_json
                )
                VALUES (%s, %s, 'running', %s, %s)
                """,
                (job_type, club_id, _utcnow(), _json_dumps(metadata)),
            )
            job_run_id = cursor.lastrowid
        conn.commit()
        return job_run_id
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn:
            conn.close()


def finish_job_run(
    job_run_id: int | None,
    status: str,
    *,
    rows_received: int | None = None,
    rows_saved: int | None = None,
    error_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not job_run_id:
        return

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            finished_at = _utcnow()
            cursor.execute(
                """
                UPDATE background_job_runs
                SET status = %s,
                    finished_at = %s,
                    duration_ms = TIMESTAMPDIFF(MICROSECOND, started_at, %s) DIV 1000,
                    rows_received = %s,
                    rows_saved = %s,
                    error_text = %s,
                    metadata_json = COALESCE(%s, metadata_json)
                WHERE id = %s
                """,
                (
                    status,
                    finished_at,
                    finished_at,
                    rows_received,
                    rows_saved,
                    error_text[:4000] if error_text else None,
                    _json_dumps(metadata),
                    job_run_id,
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


@contextmanager
def track_job_run(
    job_type: str,
    *,
    club_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[int | None]:
    job_run_id = start_job_run(job_type, club_id=club_id, metadata=metadata)
    try:
        yield job_run_id
    except Exception as exc:
        finish_job_run(job_run_id, "error", error_text=str(exc))
        raise


def get_latest_job_runs_by_club(job_types: list[str]) -> dict[int, dict[str, dict[str, Any]]]:
    if not job_types:
        return {}

    placeholders = ", ".join(["%s"] * len(job_types))
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_background_job_runs_table(cursor)
            cursor.execute(
                f"""
                SELECT r.*
                FROM background_job_runs r
                INNER JOIN (
                    SELECT club_id, job_type, MAX(started_at) AS latest_started_at
                    FROM background_job_runs
                    WHERE club_id IS NOT NULL
                      AND job_type IN ({placeholders})
                    GROUP BY club_id, job_type
                ) latest
                  ON latest.club_id = r.club_id
                 AND latest.job_type = r.job_type
                 AND latest.latest_started_at = r.started_at
                ORDER BY r.club_id, r.job_type
                """,
                tuple(job_types),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    by_club: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        club_id = int(row["club_id"])
        by_club.setdefault(club_id, {})[row["job_type"]] = row
    return by_club


def get_recent_job_runs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_background_job_runs_table(cursor)
            cursor.execute(
                """
                SELECT id, job_type, club_id, status, started_at, finished_at,
                       duration_ms, rows_received, rows_saved, error_text
                FROM background_job_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def mark_stale_job_runs(*, max_age_minutes: int = 60) -> int:
    cutoff = _utcnow() - timedelta(minutes=max_age_minutes)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_background_job_runs_table(cursor)
            cursor.execute(
                """
                UPDATE background_job_runs
                SET status = 'stale',
                    finished_at = %s,
                    duration_ms = TIMESTAMPDIFF(MICROSECOND, started_at, %s) DIV 1000,
                    error_text = COALESCE(error_text, %s)
                WHERE status = 'running'
                  AND started_at < %s
                """,
                (
                    _utcnow(),
                    _utcnow(),
                    f"Marked stale after {max_age_minutes} minutes without completion.",
                    cutoff,
                ),
            )
            marked = int(cursor.rowcount or 0)
        conn.commit()
        return marked
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
