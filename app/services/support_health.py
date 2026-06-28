from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import migrations.versions
from app.config import APP_VERSION, GIT_COMMIT
from app.core import get_db_connection


def get_expected_migration_revisions() -> list[str]:
    revisions = []
    for item in pkgutil.iter_modules(migrations.versions.__path__):
        if item.ispkg or item.name.startswith("_"):
            continue
        module = importlib.import_module(f"migrations.versions.{item.name}")
        revisions.append(getattr(module, "revision", item.name))
    return sorted(revisions)


def _fetch_applied_migrations(cursor) -> list[str]:
    try:
        cursor.execute("SELECT revision FROM schema_migrations ORDER BY revision")
        return [row["revision"] for row in cursor.fetchall()]
    except Exception:
        return []


def _fetch_count(cursor, table_name: str) -> int | None:
    try:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
        row = cursor.fetchone() or {}
        return int(row.get("cnt") or 0)
    except Exception:
        return None


def get_admin_system_health() -> dict[str, Any]:
    expected = get_expected_migration_revisions()
    conn = None
    database_ok = False
    applied: list[str] = []
    counts: dict[str, int | None] = {}
    error = None

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            row = cursor.fetchone() or {}
            database_ok = int(row.get("ok") or 0) == 1
            applied = _fetch_applied_migrations(cursor)
            counts = {
                "clubs": _fetch_count(cursor, "clubs"),
                "users": _fetch_count(cursor, "users"),
                "guests": _fetch_count(cursor, "guests"),
                "mailings": _fetch_count(cursor, "mailings"),
            }
    except Exception as exc:
        error = str(exc)
    finally:
        if conn:
            conn.close()

    pending = [revision for revision in expected if revision not in set(applied)]
    return {
        "ok": database_ok and not pending,
        "release": {
            "version": APP_VERSION,
            "commit": GIT_COMMIT or None,
        },
        "database": {
            "ok": database_ok,
            "error": error,
        },
        "migrations": {
            "expected": expected,
            "applied": applied,
            "pending": pending,
            "latest": expected[-1] if expected else None,
        },
        "counts": counts,
    }
