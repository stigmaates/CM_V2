from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from app.core import get_db_connection


@dataclass
class JobLock:
    lock_key: str
    owner_token: str
    acquired: bool


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def lock_key(job_type: str, *, club_id: int | None = None, resource_id: str | int | None = None) -> str:
    parts = [job_type]
    if club_id is not None:
        parts.append(f"club:{int(club_id)}")
    if resource_id is not None:
        parts.append(f"resource:{resource_id}")
    return ":".join(parts)


def ensure_background_job_locks_table(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS background_job_locks (
            lock_key VARCHAR(160) PRIMARY KEY,
            job_type VARCHAR(80) NOT NULL,
            club_id INT NULL,
            owner_token VARCHAR(80) NOT NULL,
            acquired_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            metadata_json JSON NULL,
            KEY idx_background_job_locks_expires (expires_at),
            KEY idx_background_job_locks_club_job (club_id, job_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)


def acquire_job_lock(
    job_type: str,
    *,
    club_id: int | None = None,
    resource_id: str | int | None = None,
    ttl_minutes: int = 60,
    metadata: dict[str, Any] | None = None,
) -> JobLock:
    key = lock_key(job_type, club_id=club_id, resource_id=resource_id)
    token = uuid.uuid4().hex
    now = _utcnow()
    expires_at = now + timedelta(minutes=ttl_minutes)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            ensure_background_job_locks_table(cursor)
            cursor.execute(
                """
                INSERT INTO background_job_locks (
                    lock_key, job_type, club_id, owner_token, acquired_at, expires_at, metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    owner_token = IF(expires_at < %s, VALUES(owner_token), owner_token),
                    acquired_at = IF(expires_at < %s, VALUES(acquired_at), acquired_at),
                    expires_at = IF(expires_at < %s, VALUES(expires_at), expires_at),
                    metadata_json = IF(expires_at < %s, VALUES(metadata_json), metadata_json)
                """,
                (
                    key,
                    job_type,
                    club_id,
                    token,
                    now,
                    expires_at,
                    _json_dumps(metadata),
                    now,
                    now,
                    now,
                    now,
                ),
            )
            cursor.execute(
                "SELECT owner_token FROM background_job_locks WHERE lock_key = %s",
                (key,),
            )
            row = cursor.fetchone() or {}
        conn.commit()
        return JobLock(lock_key=key, owner_token=token, acquired=row.get("owner_token") == token)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_job_lock(job_lock: JobLock | None) -> None:
    if not job_lock or not job_lock.acquired:
        return

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM background_job_locks
                WHERE lock_key = %s
                  AND owner_token = %s
                """,
                (job_lock.lock_key, job_lock.owner_token),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def job_lock(
    job_type: str,
    *,
    club_id: int | None = None,
    resource_id: str | int | None = None,
    ttl_minutes: int = 60,
    metadata: dict[str, Any] | None = None,
) -> Iterator[JobLock]:
    acquired = acquire_job_lock(
        job_type,
        club_id=club_id,
        resource_id=resource_id,
        ttl_minutes=ttl_minutes,
        metadata=metadata,
    )
    try:
        yield acquired
    finally:
        release_job_lock(acquired)
