"""Copy production business data to stage; keep stage schema, HVE history and job state.

Production is opened in a read-only consistent transaction. All table replacements
on stage use one transaction; no production DDL, writes, or services are involved.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import pymysql
from dotenv import dotenv_values
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
STAGE_ROOT = Path("/root/cm_stage/CM_V2")
PROD_ROOT = Path("/root/cm_v2/CM_V2")
PRESERVE = {
    "schema_migrations", "guest_score_history", "guest_lifecycle_events",
    "background_job_locks", "background_job_runs",
}
PULSE_TABLES = (
    "guest_pulse_selections", "guest_lifecycle_events", "guest_score_history",
    "guest_pulse_current", "guest_pulse_clubs", "guest_pulse_dirty",
)


def quote(name):
    return "`" + name.replace("`", "``") + "`"


def target(env_file):
    values = dotenv_values(env_file)
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    if any(not values.get(k) for k in required):
        raise ValueError("Missing database settings in environment file")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", values["DB_NAME"]):
        raise ValueError("Unsupported database name")
    return {
        "host": values["DB_HOST"], "port": int(values.get("DB_PORT") or 3306),
        "user": values["DB_USER"], "password": values["DB_PASSWORD"],
        "database": values["DB_NAME"],
    }


def validate_targets(source, stage):
    # Refuse equal names even across different hosts: aliases must never bypass this guard.
    if source["database"].casefold() == stage["database"].casefold():
        raise ValueError("Refusing equal production/stage database names")


def connect(settings):
    return pymysql.connect(**settings, charset="utf8mb4", autocommit=False,
                           connect_timeout=20, read_timeout=300, write_timeout=300)


def query(conn, sql, args=()):
    with conn.cursor(DictCursor) as cursor:
        cursor.execute(sql, args)
        return list(cursor.fetchall())


def inventory(conn):
    return {r["TABLE_NAME"]: r for r in query(conn, """
        SELECT TABLE_NAME,TABLE_TYPE,ENGINE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME
    """)}


def columns(conn, table):
    return query(conn, """SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION""", (table,))


def make_plan(source, stage):
    source_tables, stage_tables = inventory(source), inventory(stage)
    plan = {}
    for name, info in source_tables.items():
        if name in PRESERVE or name.startswith("guest_pulse_"):
            continue
        if info["TABLE_TYPE"] != "BASE TABLE":
            continue
        if name not in stage_tables:
            raise ValueError(f"Stage schema is missing table: {name}; migrate stage before copying")
        if info["ENGINE"] != "InnoDB" or stage_tables[name]["ENGINE"] != "InnoDB":
            raise ValueError(f"Atomic mirroring requires InnoDB: {name}")
        source_columns = {r["COLUMN_NAME"]: r for r in columns(source, name)}
        stage_columns = {r["COLUMN_NAME"]: r for r in columns(stage, name)}
        for key, column in source_columns.items():
            if key not in stage_columns or column["COLUMN_TYPE"] != stage_columns[key]["COLUMN_TYPE"]:
                raise ValueError(f"Incompatible stage column: {name}.{key}")
        for key, column in stage_columns.items():
            if (key not in source_columns and column["IS_NULLABLE"] != "YES"
                    and column["COLUMN_DEFAULT"] is None and "auto_increment" not in column["EXTRA"]
                    and not any(k in column["EXTRA"] for k in ("STORED GENERATED", "VIRTUAL GENERATED"))):
                raise ValueError(f"Required stage-only column has no default: {name}.{key}")
        plan[name] = [key for key, col in source_columns.items() if not any(k in col["EXTRA"] for k in ("STORED GENERATED", "VIRTUAL GENERATED"))]
    for required in ("clubs", "guests", "guest_sessions", "guest_balance_topups"):
        if required not in plan:
            raise ValueError(f"Missing business source table: {required}")
    return plan


def primary_key(conn, table):
    return [row["COLUMN_NAME"] for row in query(conn, """
        SELECT COLUMN_NAME FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME='PRIMARY'
        ORDER BY SEQ_IN_INDEX
    """, (table,))]


def source_batches(source, table, names, batch_size):
    """Fully consume a bounded SELECT before writing stage, without an open stream."""
    keys = primary_key(source, table)
    if not set(keys).issubset(names):
        keys = []
    projection = ",".join(quote(name) for name in names)
    order = ",".join(quote(name) for name in (keys or names))
    positions = [names.index(key) for key in keys]
    last, offset = None, 0
    while True:
        where, params = "", []
        if keys and last is not None:
            where = f" WHERE ({order}) > ({','.join(['%s'] * len(keys))})"
            params.extend(last)
        sql = f"SELECT {projection} FROM {quote(table)}{where} ORDER BY {order} LIMIT %s"
        params.append(batch_size)
        if not keys:
            sql += " OFFSET %s"
            params.append(offset)
        with source.cursor() as cursor:
            cursor.execute(sql, params)
            batch = cursor.fetchall()
        if not batch:
            return
        yield batch
        if keys:
            last = tuple(batch[-1][index] for index in positions)
        offset += len(batch)
        if len(batch) < batch_size:
            return


def safe_error(exc):
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    return type(exc).__name__ + (f" (code {code})" if code is not None else "")


def replace_tables(source, stage, plan, *, reset_pulse=False, batch_size=500):
    """No DDL/TRUNCATE: a failure rolls back every replaced stage table together."""
    source.rollback()
    stage.rollback()
    with source.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    copied = {}
    table = "transaction setup"
    try:
        with stage.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        stage.begin()
        for table, names in plan.items():
            print(f"Copying {table}...", flush=True)
            projection = ",".join(quote(name) for name in names)
            insert = f"INSERT INTO {quote(table)} ({projection}) VALUES ({','.join(['%s'] * len(names))})"
            with stage.cursor() as destination:
                destination.execute(f"DELETE FROM {quote(table)}")
                count = 0
                for batch in source_batches(source, table, names, batch_size):
                    destination.executemany(insert, batch)
                    count += len(batch)
            actual = query(stage, f"SELECT COUNT(*) AS cnt FROM {quote(table)}")[0]["cnt"]
            if actual != count:
                raise ValueError(f"Stage row count mismatch: {table}")
            copied[table] = count
            print(f"Copied {table}: {count} rows (not committed yet)", flush=True)
        if reset_pulse:
            with stage.cursor() as cursor:
                for table in PULSE_TABLES:
                    cursor.execute(f"DELETE FROM {quote(table)}")
        stage.commit()
    except BaseException as exc:
        print(f"Copy failed at {table}: {safe_error(exc)}", file=sys.stderr, flush=True)
        # Cleanup on a lost connection must not replace the original exception.
        with suppress(pymysql.Error):
            stage.rollback()
        raise
    finally:
        with suppress(pymysql.Error):
            source.rollback()
        with suppress(pymysql.Error):
            with stage.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    return copied


def stage_environment():
    env = os.environ.copy()
    env.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None})
    env["DISABLE_OUTBOUND_MESSAGES"] = "1"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    return env


def run_rebuild(script, arguments, env):
    print(f"Starting {script}; rebuilding can take several minutes...", flush=True)
    command = [sys.executable, str(ROOT / "scripts" / script), *arguments]
    with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        while True:
            try:
                stdout, _ = process.communicate(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print(f"{script}: still running; please wait.", flush=True)
        if process.returncode:
            raise ValueError(f"{script} failed (exit {process.returncode}); data copy is already committed")
        # These three fixed scripts report aggregate counts only on successful runs.
        if stdout.strip():
            print(stdout.strip(), flush=True)
        print(f"Finished {script}", flush=True)


def copy_or_resume(source, stage, plan, *, rebuild_only=False, reset_pulse=False):
    if rebuild_only:
        print("Resuming rebuild on existing stage data; no business tables or HVE history are deleted.", flush=True)
        return {table: query(stage, f"SELECT COUNT(*) AS cnt FROM {quote(table)}")[0]["cnt"] for table in plan}
    copied = replace_tables(source, stage, plan, reset_pulse=reset_pulse)
    print(f"Business data committed atomically; tables={len(copied)}, rows={sum(copied.values())}", flush=True)
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only schema/target check")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild-only", action="store_true", help="Resume after a confirmed committed copy; skip copying and history deletion")
    parser.add_argument("--reset-pulse-history", action="store_true", help="Initial copy only: reconstruct HVE from production events")
    args = parser.parse_args()
    if ROOT.resolve() != STAGE_ROOT.resolve():
        raise ValueError("Run only from the verified /root/cm_stage/CM_V2 checkout")
    if args.apply == args.check:
        raise ValueError("Choose exactly one of --check or --apply")
    if args.rebuild_only and not args.apply:
        raise ValueError("--rebuild-only requires --apply")
    source_settings, stage_settings = target(PROD_ROOT / ".env"), target(ROOT / ".env")
    validate_targets(source_settings, stage_settings)
    if args.apply and not (ROOT / ".stage-no-outbound").is_file():
        raise ValueError("Refusing mirror without the stage outbound stop file")
    source = connect(source_settings)
    stage = None
    acquired = False
    try:
        stage = connect(stage_settings)
        plan = make_plan(source, stage)
        print(f"Different database schemas verified; compatible business tables: {len(plan)}", flush=True)
        if args.check:
            print("Read-only mirror preflight OK. No data or settings changed.")
            return 0
        acquired = bool(query(stage, "SELECT GET_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())),0) AS acquired")[0]["acquired"])
        if not acquired:
            print("Stage mirror already running; skipped.")
            return 0
        copied = copy_or_resume(source, stage, plan, rebuild_only=args.rebuild_only, reset_pulse=args.reset_pulse_history)
        env = stage_environment()
        for script, arguments in (
            ("rebuild_user_portrait.py", []),
            ("rebuild_guest_pulse.py", ["--backfill"] if args.reset_pulse_history else ["--force"]),
            ("check_guest_pulse.py", []),
        ):
            run_rebuild(script, arguments, env)
        state = {"completed_at_utc": datetime.now(UTC).isoformat(), "tables": copied, "outbound_messages": "blocked"}
        path = ROOT / ".stage-mirror-state.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        print("Stage mirror and HVE refresh OK; outbound messages blocked.")
        return 0
    finally:
        if acquired:
            with suppress(pymysql.Error):
                query(stage, "SELECT RELEASE_LOCK(CONCAT('stage-mirror:',MD5(DATABASE())))")
        if stage is not None:
            stage.close()
        source.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Driver errors can embed statements/credentials. Never dump them to the journal.
        print(f"Stage mirror failed: {safe_error(exc)}. Previous transaction was rolled back if uncommitted.", file=sys.stderr)
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
