from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection  # noqa: E402
import migrations.versions  # noqa: E402


def _ensure_schema_migrations_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            revision VARCHAR(120) PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def _applied_revisions(cursor) -> set[str]:
    cursor.execute("SELECT revision FROM schema_migrations")
    return {row["revision"] for row in cursor.fetchall()}


def _migration_modules():
    modules = []
    for item in pkgutil.iter_modules(migrations.versions.__path__):
        if item.ispkg or item.name.startswith("_"):
            continue
        module = importlib.import_module(f"migrations.versions.{item.name}")
        revision = getattr(module, "revision", item.name)
        modules.append((revision, module))
    return sorted(modules, key=lambda pair: pair[0])


def migrate() -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            _ensure_schema_migrations_table(cursor)
            applied = _applied_revisions(cursor)
            pending = [
                (revision, module)
                for revision, module in _migration_modules()
                if revision not in applied
            ]

            if not pending:
                print("No pending migrations.")
                return 0

            for revision, module in pending:
                print(f"Applying migration {revision}...")
                module.upgrade(cursor)
                cursor.execute(
                    "INSERT INTO schema_migrations (revision) VALUES (%s)",
                    (revision,),
                )
                conn.commit()
                print(f"Applied migration {revision}.")

        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(migrate())
