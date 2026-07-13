from app.services.rate_limit import clear_rate_limits, is_rate_limited


def test_rate_limit_blocks_after_limit():
    clear_rate_limits()
    now = 100.0

    assert is_rate_limited("login:1", limit=2, window_seconds=60, now_func=lambda: now) is False
    assert is_rate_limited("login:1", limit=2, window_seconds=60, now_func=lambda: now + 1) is False
    assert is_rate_limited("login:1", limit=2, window_seconds=60, now_func=lambda: now + 2) is True


def test_rate_limit_expires_old_attempts():
    clear_rate_limits()

    assert is_rate_limited("login:2", limit=1, window_seconds=60, now_func=lambda: 100.0) is False
    assert is_rate_limited("login:2", limit=1, window_seconds=60, now_func=lambda: 161.0) is False
