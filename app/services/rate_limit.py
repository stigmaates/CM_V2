from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from flask import has_request_context, request

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def client_ip() -> str:
    if not has_request_context():
        return "unknown"
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"


def is_rate_limited(
    key: str,
    *,
    limit: int,
    window_seconds: int,
    now_func: Callable[[], float] | None = None,
) -> bool:
    now = (now_func or time.monotonic)()
    bucket = _BUCKETS[key]
    cutoff = now - window_seconds

    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= limit:
        return True

    bucket.append(now)
    return False


def clear_rate_limits() -> None:
    _BUCKETS.clear()
