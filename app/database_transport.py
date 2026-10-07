"""A single verified TLS policy for web, bots, sync workers and stage mirroring."""

import os
import ssl
from functools import lru_cache


def database_ssl(values=None):
    values = os.environ if values is None else values
    ca = (values.get("DB_SSL_CA") or "").strip() or None
    return _context(ca)


@lru_cache(maxsize=8)
def _context(ca):
    # System trust or an explicitly provisioned CA. Never silently downgrade on failure.
    context = ssl.create_default_context(cafile=ca)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
