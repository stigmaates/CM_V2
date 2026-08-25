from datetime import datetime

import pytest

from app.services.timezones import (
    DEFAULT_CLUB_TIMEZONE,
    club_local_datetime_to_utc,
    get_club_local_now,
    get_club_timezone_label,
    validate_club_timezone,
)


def test_ufa_timezone_is_available_for_club_settings():
    assert validate_club_timezone("Asia/Yekaterinburg") == "Asia/Yekaterinburg"
    assert get_club_timezone_label("Asia/Yekaterinburg") == "Екатеринбург / Уфа — UTC+5"


def test_empty_timezone_uses_moscow_default():
    assert validate_club_timezone("") == DEFAULT_CLUB_TIMEZONE


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="часовой пояс"):
        validate_club_timezone("Mars/Olympus")


def test_club_local_now_returns_naive_database_compatible_datetime():
    value = get_club_local_now("Asia/Yekaterinburg")

    assert isinstance(value, datetime)
    assert value.tzinfo is None


def test_ufa_noon_converts_to_seven_utc():
    local_value = datetime(2026, 8, 25, 12, 0)

    assert club_local_datetime_to_utc(local_value, "Asia/Yekaterinburg") == datetime(2026, 8, 25, 7, 0)
