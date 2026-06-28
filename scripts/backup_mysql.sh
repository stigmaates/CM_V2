#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
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

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/${DB_NAME}_${timestamp}.sql.gz"

MYSQL_PWD="$DB_PASSWORD" mysqldump \
  --no-defaults \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --user="$DB_USER" \
  --skip-opt \
  --single-transaction \
  --skip-lock-tables \
  --no-tablespaces \
  --quick \
  --add-drop-table \
  --create-options \
  --extended-insert \
  --set-charset \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  "$DB_NAME" | gzip -c > "$backup_file"

echo "$backup_file"
