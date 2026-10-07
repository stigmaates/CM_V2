"""Non-secret deployment identities: runtime users need not read the other .env."""

import json
import os
import stat
from pathlib import Path

from dotenv import dotenv_values

IDENTITIES_FILE = Path("/etc/cyber-bonus/database-identities.json")


def peer_database_identity(environment, *, legacy_env):
    if not IDENTITIES_FILE.exists():
        # Compatibility while root-based deployments are being migrated.
        return dotenv_values(legacy_env)
    descriptor = os.open(IDENTITIES_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Deployment identities must be root-owned and not writable by runtime users")
        values = json.load(stream)[environment]
    if set(values) != {"DB_HOST", "DB_PORT", "DB_NAME"} or not values["DB_HOST"] or not values["DB_NAME"]:
        raise ValueError("Invalid non-secret deployment identity")
    return values
