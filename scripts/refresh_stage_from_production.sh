#!/usr/bin/env bash
set -euo pipefail

STAGE_ROOT="${STAGE_ROOT:-/root/cm_stage/CM_V2}"
PROD_ROOT="${PROD_ROOT:-/root/cm_v2/CM_V2}"
STAGE_ENV_FILE="${STAGE_ENV_FILE:-$STAGE_ROOT/.env}"
PROD_ENV_FILE="${PROD_ENV_FILE:-$PROD_ROOT/.env}"
STAGE_WEB_SERVICE="${STAGE_WEB_SERVICE:-clubmodule-stage.service}"
STAGE_BOT_SERVICE="${STAGE_BOT_SERVICE:-clubmodule-stage-bot.service}"
PYTHON_BIN="${PYTHON_BIN:-$STAGE_ROOT/venv/bin/python}"
BACKUP_DIR="${BACKUP_DIR:-$STAGE_ROOT/backups/prod-refresh}"

if [[ "$(cd "$STAGE_ROOT" && pwd)" != "$(pwd)" ]]; then
  echo "Run this script from $STAGE_ROOT" >&2
  exit 1
fi

for file in "$STAGE_ENV_FILE" "$PROD_ENV_FILE"; do
  if [[ ! -f "$file" ]]; then
    echo "Environment file not found: $file" >&2
    exit 1
  fi
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

read_env_exports() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
from __future__ import annotations

import shlex
import sys

from dotenv import dotenv_values

env_file, prefix = sys.argv[1], sys.argv[2]
names = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
values = dotenv_values(env_file)
for name in names:
    value = values.get(name)
    if value is not None:
        print(f"export {prefix}_{name}={shlex.quote(str(value))}")
PY
}

eval "$(read_env_exports "$STAGE_ENV_FILE" STAGE)"
eval "$(read_env_exports "$PROD_ENV_FILE" PROD)"

required=(
  STAGE_DB_HOST STAGE_DB_PORT STAGE_DB_USER STAGE_DB_PASSWORD STAGE_DB_NAME
  PROD_DB_HOST PROD_DB_PORT PROD_DB_USER PROD_DB_PASSWORD PROD_DB_NAME
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required value: $name" >&2
    exit 1
  fi
done

if [[ "$STAGE_DB_HOST:$STAGE_DB_PORT/$STAGE_DB_NAME" == "$PROD_DB_HOST:$PROD_DB_PORT/$PROD_DB_NAME" ]]; then
  echo "Refusing to continue: stage and production database targets are identical." >&2
  exit 1
fi

echo "This will overwrite stage database '$STAGE_DB_NAME' with production database '$PROD_DB_NAME'."
echo "Stage bot will be stopped and left stopped. Production services will not be touched."
echo "Type REFRESH_STAGE to continue:"
read -r confirmation
if [[ "$confirmation" != "REFRESH_STAGE" ]]; then
  echo "Refresh cancelled." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Stopping stage bot..."
systemctl stop "$STAGE_BOT_SERVICE"

echo "Creating stage backup..."
stage_backup="$(ENV_FILE="$STAGE_ENV_FILE" BACKUP_DIR="$BACKUP_DIR" PYTHON_BIN="$PYTHON_BIN" bash "$STAGE_ROOT/scripts/backup_mysql.sh")"
echo "Stage backup: $stage_backup"

echo "Creating production database dump..."
prod_backup="$(ENV_FILE="$PROD_ENV_FILE" BACKUP_DIR="$BACKUP_DIR" PYTHON_BIN="$PYTHON_BIN" bash "$STAGE_ROOT/scripts/backup_mysql.sh")"
echo "Production dump: $prod_backup"

echo "Stopping stage web during restore..."
systemctl stop "$STAGE_WEB_SERVICE"

echo "Dropping existing stage tables..."
stage_tables="$(
  MYSQL_PWD="$STAGE_DB_PASSWORD" mysql \
    --host="$STAGE_DB_HOST" \
    --port="$STAGE_DB_PORT" \
    --user="$STAGE_DB_USER" \
    --batch \
    --skip-column-names \
    --default-character-set=utf8mb4 \
    -e "SELECT GROUP_CONCAT(CONCAT('\`', TABLE_NAME, '\`') SEPARATOR ',') FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$STAGE_DB_NAME';"
)"
if [[ -n "$stage_tables" && "$stage_tables" != "NULL" ]]; then
  MYSQL_PWD="$STAGE_DB_PASSWORD" mysql \
    --host="$STAGE_DB_HOST" \
    --port="$STAGE_DB_PORT" \
    --user="$STAGE_DB_USER" \
    --default-character-set=utf8mb4 \
    "$STAGE_DB_NAME" \
    -e "SET FOREIGN_KEY_CHECKS=0; DROP TABLE IF EXISTS $stage_tables; SET FOREIGN_KEY_CHECKS=1;"
fi

echo "Restoring production dump into stage database..."
gzip -dc "$prod_backup" | MYSQL_PWD="$STAGE_DB_PASSWORD" mysql \
  --host="$STAGE_DB_HOST" \
  --port="$STAGE_DB_PORT" \
  --user="$STAGE_DB_USER" \
  --default-character-set=utf8mb4 \
  "$STAGE_DB_NAME"

echo "Applying stage migrations..."
"$PYTHON_BIN" "$STAGE_ROOT/scripts/migrate.py"
"$PYTHON_BIN" "$STAGE_ROOT/scripts/migrate.py" --dry-run

echo "Starting stage web..."
systemctl start "$STAGE_WEB_SERVICE"

echo "Stage refresh completed."
echo "Stage backup: $stage_backup"
echo "Production dump used for refresh: $prod_backup"
echo "Stage bot remains stopped: $STAGE_BOT_SERVICE"
