"""Atomic login limits shared by all workers. Stores hashes, never passwords/logins."""

import hashlib
import os
import sqlite3
import time
from pathlib import Path

from flask import current_app


def login_is_limited(ip, login, *, now=None):
    now = time.time() if now is None else now
    path = Path(current_app.config["LOGIN_RATE_LIMIT_FILE"])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    buckets = [(f"ip:{ip}", 10, 300)]
    if login:
        buckets.append((f"account:{login.casefold()}", 20, 900))
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)"
        )
        connection.execute("DELETE FROM attempts WHERE expires <= ?", (now,))
        limited = False
        for value, limit, window in buckets:
            key = hashlib.sha256(value.encode()).hexdigest()
            row = connection.execute("SELECT count FROM attempts WHERE key=?", (key,)).fetchone()
            if row and row[0] >= limit:
                limited = True
            # Keep counting the account even when an individual IP is blocked.
            connection.execute(
                "INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=min(count+1,1000000)",
                (key, now + window),
            )
        connection.commit()
        return limited
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
