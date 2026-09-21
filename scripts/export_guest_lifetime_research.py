#!/usr/bin/env python3
"""Create an anonymized, read-only export for guest lifetime research.

The script is intended to run on an application host that already has database
credentials in its environment.  It never writes to the database and excludes
names, phones, Telegram identifiers, birthdays and other direct identifiers.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import tarfile
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import get_db_connection  # noqa: E402, I001


EXPORT_VERSION = 1
DIRECT_IDENTIFIER_NAMES = {
    "fio",
    "name",
    "guest_name",
    "phone",
    "email",
    "telegram_id",
    "telegram_username",
    "birth_date",
    "birthday",
}
SAFE_QUERY_PREFIXES = ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH")
TABLES_OF_INTEREST = (
    "clubs",
    "guests",
    "guest_sessions",
    "guest_balance_topups",
    "operations_log",
)


def _first_sql_keyword(sql: str) -> str:
    without_comments = re.sub(r"/\*.*?\*/|--[^\n]*|#[^\n]*", " ", sql, flags=re.S)
    match = re.search(r"[A-Za-z]+", without_comments)
    return match.group(0).upper() if match else ""


def ensure_read_only_sql(sql: str) -> None:
    keyword = _first_sql_keyword(sql)
    if keyword not in SAFE_QUERY_PREFIXES:
        raise ValueError(f"Only read-only SQL is allowed, got {keyword or 'empty SQL'}")
    lowered = re.sub(r"\s+", " ", sql.lower())
    forbidden = (
        " into outfile",
        " into dumpfile",
        " for update",
        " lock in share mode",
        " load_file(",
    )
    if any(token in lowered for token in forbidden):
        raise ValueError("Potentially mutating or file-reading SQL is not allowed")


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def csv_value(value: Any) -> Any:
    value = json_value(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ReadOnlyDatabase:
    def __init__(self, connection):
        self.connection = connection

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        ensure_read_only_sql(sql)
        with self.connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return list(cursor.fetchall() or [])

    def stream(self, sql: str, params: Sequence[Any] = (), batch_size: int = 2000) -> Iterator[dict[str, Any]]:
        ensure_read_only_sql(sql)
        cursor = self.connection.cursor(pymysql.cursors.SSDictCursor)
        try:
            cursor.execute(sql, tuple(params))
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    return
                yield from rows
        finally:
            cursor.close()


@contextmanager
def read_only_database():
    connection = get_db_connection()
    connection.autocommit(False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION READ ONLY")
        yield ReadOnlyDatabase(connection)
    finally:
        connection.rollback()
        connection.close()


def existing_tables(db: ReadOnlyDatabase) -> set[str]:
    rows = db.fetch_all(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
        """
    )
    return {str(row["TABLE_NAME"]) for row in rows}


def table_columns(db: ReadOnlyDatabase, table_name: str) -> set[str]:
    rows = db.fetch_all(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    return {str(row["COLUMN_NAME"]) for row in rows}


def schema_audit(db: ReadOnlyDatabase) -> dict[str, Any]:
    columns = db.fetch_all(
        """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME IN (%s, %s, %s, %s, %s)
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        TABLES_OF_INTEREST,
    )
    indexes = db.fetch_all(
        """
        SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME IN (%s, %s, %s, %s, %s)
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        """,
        TABLES_OF_INTEREST,
    )
    related = db.fetch_all(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND (
            LOWER(TABLE_NAME) LIKE '%%booking%%'
            OR LOWER(TABLE_NAME) LIKE '%%reservation%%'
            OR LOWER(TABLE_NAME) LIKE '%%room%%'
            OR LOWER(TABLE_NAME) LIKE '%%zone%%'
            OR LOWER(TABLE_NAME) LIKE '%%bar%%'
          )
        ORDER BY TABLE_NAME
        """
    )
    return {
        "tables": sorted(existing_tables(db)),
        "columns": [{key: json_value(value) for key, value in row.items()} for row in columns],
        "indexes": [{key: json_value(value) for key, value in row.items()} for row in indexes],
        "possible_auxiliary_tables": [str(row["TABLE_NAME"]) for row in related],
    }


def scalar(db: ReadOnlyDatabase, sql: str, params: Sequence[Any] = ()) -> Any:
    rows = db.fetch_all(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def quality_audit(db: ReadOnlyDatabase, tables: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z"}
    if "guest_sessions" in tables:
        result["sessions_by_club"] = [
            {key: json_value(value) for key, value in row.items()}
            for row in db.fetch_all(
                """
                SELECT
                    club_id,
                    COUNT(*) AS rows_total,
                    COUNT(DISTINCT guest_id) AS guests_identified,
                    SUM(guest_id IS NULL) AS rows_without_guest,
                    SUM(date_start IS NULL) AS rows_without_start,
                    SUM(date_stop IS NULL) AS rows_without_stop,
                    SUM(date_stop IS NOT NULL AND date_start IS NOT NULL AND date_stop <= date_start) AS nonpositive_rows,
                    SUM(date_stop IS NOT NULL AND date_start IS NOT NULL AND date_stop > DATE_ADD(date_start, INTERVAL 24 HOUR)) AS rows_over_24h,
                    MIN(date_start) AS first_start,
                    MAX(date_start) AS last_start,
                    MAX(date_stop) AS last_stop
                FROM guest_sessions
                GROUP BY club_id
                ORDER BY club_id
                """
            )
        ]
    if "guests" in tables:
        result["guests_by_club"] = [
            {key: json_value(value) for key, value in row.items()}
            for row in db.fetch_all(
                """
                SELECT club_id, COUNT(*) AS rows_total, COUNT(DISTINCT guest_id) AS guests_unique,
                       SUM(guest_id IS NULL) AS rows_without_guest_id,
                       MIN(date_insert) AS first_insert, MAX(date_insert) AS last_insert
                FROM guests
                GROUP BY club_id
                ORDER BY club_id
                """
            )
        ]
    if "guest_balance_topups" in tables:
        result["topups_by_club"] = [
            {key: json_value(value) for key, value in row.items()}
            for row in db.fetch_all(
                """
                SELECT club_id, COUNT(*) AS rows_total, COUNT(DISTINCT guest_id) AS guests_identified,
                       SUM(guest_id IS NULL) AS rows_without_guest,
                       SUM(amount <= 0) AS nonpositive_rows,
                       SUM(amount > 1000000) AS rows_over_1m,
                       MIN(topup_at) AS first_topup, MAX(topup_at) AS last_topup,
                       SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS positive_amount
                FROM guest_balance_topups
                GROUP BY club_id
                ORDER BY club_id
                """
            )
        ]
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_gz(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> int:
    lowered = {name.lower() for name in fieldnames}
    unsafe = sorted(lowered & DIRECT_IDENTIFIER_NAMES)
    if unsafe:
        raise ValueError(f"Direct identifiers cannot be exported: {', '.join(unsafe)}")
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: csv_value(row.get(name)) for name in fieldnames})
            count += 1
    return count


def select_existing(columns: set[str], choices: Sequence[str]) -> list[str]:
    return [name for name in choices if name in columns]


def test_like_sql(columns: set[str]) -> str:
    if "fio" not in columns:
        return "0"
    return "LOWER(COALESCE(fio, '')) REGEXP '(тест|test|служеб|админ)'"


def export_data(db: ReadOnlyDatabase, output_dir: Path, tables: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if "clubs" in tables:
        columns = table_columns(db, "clubs")
        fields = select_existing(columns, ("club_id", "timezone", "service_enabled", "cooperation_started_at", "created_at"))
        if "club_id" not in fields:
            raise RuntimeError("clubs.club_id is required")
        counts["clubs"] = write_csv_gz(
            output_dir / "clubs.csv.gz",
            fields,
            db.stream(f"SELECT {', '.join(fields)} FROM clubs ORDER BY club_id"),
        )

    if "guests" in tables:
        columns = table_columns(db, "guests")
        base_fields = select_existing(columns, ("club_id", "guest_id", "date_insert", "created_at"))
        if not {"club_id", "guest_id"}.issubset(base_fields):
            raise RuntimeError("guests.club_id and guests.guest_id are required")
        telegram_expr = "(telegram_id IS NOT NULL)" if "telegram_id" in columns else "0"
        select_parts = [*base_fields, f"{telegram_expr} AS telegram_linked", f"{test_like_sql(columns)} AS test_like"]
        fields = [*base_fields, "telegram_linked", "test_like"]
        counts["guests"] = write_csv_gz(
            output_dir / "guests.csv.gz",
            fields,
            db.stream(f"SELECT {', '.join(select_parts)} FROM guests ORDER BY club_id, guest_id"),
        )

    if "guest_sessions" in tables:
        columns = table_columns(db, "guest_sessions")
        fields = select_existing(columns, ("id", "club_id", "guest_id", "date_start", "date_stop"))
        if not {"club_id", "guest_id", "date_start", "date_stop"}.issubset(fields):
            raise RuntimeError("guest_sessions does not have the required research columns")
        counts["sessions"] = write_csv_gz(
            output_dir / "sessions.csv.gz",
            fields,
            db.stream(
                f"SELECT {', '.join(fields)} FROM guest_sessions "
                "WHERE guest_id IS NOT NULL ORDER BY club_id, guest_id, date_start"
            ),
        )

    if "guest_balance_topups" in tables:
        columns = table_columns(db, "guest_balance_topups")
        fields = select_existing(columns, ("club_id", "topup_id", "guest_id", "amount", "topup_at"))
        if not {"club_id", "guest_id", "amount", "topup_at"}.issubset(fields):
            raise RuntimeError("guest_balance_topups does not have the required research columns")
        counts["topups"] = write_csv_gz(
            output_dir / "topups.csv.gz",
            fields,
            db.stream(
                f"SELECT {', '.join(fields)} FROM guest_balance_topups "
                "WHERE guest_id IS NOT NULL ORDER BY club_id, guest_id, topup_at"
            ),
        )
    return counts


def build_archive(output_dir: Path) -> Path:
    archive = output_dir.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(output_dir, arcname=output_dir.name)
    return archive


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp") / f"guest_lifetime_export_{datetime.utcnow():%Y%m%dT%H%M%SZ}",
        help="Directory for anonymized files (default: /tmp/guest_lifetime_export_TIMESTAMP)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    with read_only_database() as db:
        tables = existing_tables(db)
        write_json(output_dir / "schema_audit.json", schema_audit(db))
        write_json(output_dir / "quality_audit.json", quality_audit(db, tables))
        counts = export_data(db, output_dir, tables)

    files = []
    for path in sorted(output_dir.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "export_version": EXPORT_VERSION,
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "read_only": True,
        "contains_direct_identifiers": False,
        "row_counts": counts,
        "files": files,
    }
    write_json(output_dir / "manifest.json", manifest)
    archive = build_archive(output_dir)
    print(json.dumps({"output_dir": str(output_dir), "archive": str(archive), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
