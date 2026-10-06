"""Read production metadata from stage to prepare a release; never deploy or migrate.

No API keys, database credentials or guest records are printed. Production SQL
runs in a READ ONLY transaction. No schema bootstrap or migrate --dry-run (which
can create schema_migrations) is used here.
"""

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from pymysql.cursors import DictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.stage import PRODUCTION_ENV, ROOT, require_stage_environment
from scripts.mirror_production_to_stage import connect, target, validate_targets


def command(argv, *, cwd=None):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=20)
    return result.returncode, result.stdout.strip()


def candidate_revisions(root):
    revisions = []
    for path in sorted((root / "migrations/versions").glob("[0-9]*.py")):
        revision = path.stem
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "revision" for t in node.targets
            ):
                revision = ast.literal_eval(node.value)
        revisions.append(revision)
    return revisions


def database_report(conn, revisions):
    with conn.cursor(DictCursor) as cur:
        cur.execute("START TRANSACTION READ ONLY")
        try:
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='schema_migrations'"
            )
            exists = bool(cur.fetchone())
            applied = set()
            if exists:
                cur.execute("SELECT revision FROM schema_migrations")
                applied = {row["revision"] for row in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS clubs, COALESCE(MAX(club_id),0)+1 AS next_club_id FROM clubs")
            result = dict(cur.fetchone())
            cur.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clubs' AND COLUMN_NAME='integration_provider'"
            )
            if cur.fetchone():
                cur.execute("SELECT integration_provider,COUNT(*) AS clubs FROM clubs GROUP BY integration_provider")
                result["providers"] = cur.fetchall()
            result.update(
                pending_migrations=[r for r in revisions if r not in applied],
                unknown_applied_migrations=sorted(applied - set(revisions)),
                schema_migrations_exists=exists,
            )
            return result
        finally:
            conn.rollback()


def run():
    require_stage_environment()
    prod_root = PRODUCTION_ENV.parent
    prod_env = dotenv_values(PRODUCTION_ENV)
    prod_target, stage_target = target(PRODUCTION_ENV), target(ROOT / ".env")
    validate_targets(prod_target, stage_target)
    code, prod_commit = command(["git", "rev-parse", "HEAD"], cwd=prod_root)
    if code or len(prod_commit) != 40:
        raise ValueError("Production Git revision could not be read")
    _, candidate_commit = command(["git", "rev-parse", "HEAD"], cwd=ROOT)
    _, branch = command(["git", "branch", "--show-current"], cwd=prod_root)
    dirty_code, dirty = command(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=no"], cwd=prod_root)
    contains, _ = command(["git", "merge-base", "--is-ancestor", prod_commit, "HEAD"], cwd=ROOT)
    diff_code, changes = command(["git", "diff", "--name-only", prod_commit, "HEAD"], cwd=ROOT)
    _, web = command(
        ["systemctl", "show", "clubmodule.service", "-p", "ActiveState", "-p", "WorkingDirectory", "-p", "User"]
    )
    _, scheduler = command(["systemctl", "is-active", "clubmodule-gizmo-sync.timer"])
    conn = connect(prod_target)
    try:
        database = database_report(conn, candidate_revisions(ROOT))
    finally:
        conn.close()
    return dict(
        status="read_only_complete",
        checked_at_utc=datetime.now(UTC).isoformat(),
        production_commit=prod_commit,
        production_branch=branch,
        candidate_commit=candidate_commit,
        production_tracked_dirty=bool(dirty) if not dirty_code else None,
        candidate_contains_production=(contains == 0) if contains in (0, 1) else None,
        changed_files_count=len(changes.splitlines()) if diff_code == 0 else None,
        production_web=dict(line.split("=", 1) for line in web.splitlines() if "=" in line),
        production_gizmo_opt_in=prod_env.get("GIZMO_ENABLED") == "1",
        production_gizmo_timer=scheduler,
        database=database,
        deployed=False,
        limitation="Release inputs only; backup, migration compatibility and rollback still require review",
    )


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print("Проверка остановлена: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
