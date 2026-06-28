#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/backup.sql.gz" >&2
  exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

env_exports="$("$PYTHON_BIN" - "$ENV_FILE" <<'PY'
from __future__ import annotations

import shlex
import sys

from dotenv import dotenv_values

names = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
values = dotenv_values(sys.argv[1])
for name in names:
    value = values.get(name)
    if value is not None:
        print(f"export {name}={shlex.quote(str(value))}")
PY
)" || exit 1
eval "$env_exports"

required=(DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
done

echo "About to restore $BACKUP_FILE into database '$DB_NAME' on '$DB_HOST:$DB_PORT'."
echo "Type RESTORE to continue:"
read -r confirmation
if [[ "$confirmation" != "RESTORE" ]]; then
  echo "Restore cancelled." >&2
  exit 1
fi

if [[ "$BACKUP_FILE" == *.gz ]]; then
  gzip -dc "$BACKUP_FILE" | MYSQL_PWD="$DB_PASSWORD" mysql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --default-character-set=utf8mb4 \
    "$DB_NAME"
else
  MYSQL_PWD="$DB_PASSWORD" mysql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --default-character-set=utf8mb4 \
    "$DB_NAME" < "$BACKUP_FILE"
fi

echo "Restore completed."
