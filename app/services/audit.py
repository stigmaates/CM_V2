from __future__ import annotations

import json
from typing import Any

from flask import has_request_context, request, session

from app.core import get_db_connection


def _safe_json(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def record_audit_event(
    *,
    action: str,
    club_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
    actor_role: str | None = None,
) -> None:
    """Best-effort audit log writer.

    Audit failures must not break owner/admin workflows. Missing migrations,
    transient DB errors, or malformed optional details are intentionally ignored.
    """
    if not action:
        return

    ip = None
    user_agent = None
    if has_request_context():
        actor_user_id = actor_user_id if actor_user_id is not None else session.get("user_id")
        actor_role = actor_role if actor_role is not None else session.get("role")
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent")

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    club_id,
                    actor_user_id,
                    actor_role,
                    action,
                    entity_type,
                    entity_id,
                    details_json,
                    ip,
                    user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    club_id,
                    actor_user_id,
                    actor_role,
                    action,
                    entity_type,
                    str(entity_id) if entity_id is not None else None,
                    _safe_json(details),
                    ip,
                    user_agent,
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
