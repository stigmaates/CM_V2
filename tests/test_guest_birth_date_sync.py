from datetime import date, datetime

from scripts.sync_guests import parse_date as parse_initial_date
from scripts.sync_guests_incremental import filter_changed_guests, parse_date as parse_incremental_date


def test_guest_birth_date_parsers_accept_langame_datetime():
    expected = date(1990, 1, 15)

    for parse_date in (parse_initial_date, parse_incremental_date):
        assert parse_date("1990-01-15") == expected
        assert parse_date("1990-01-15 00:00:00") == expected
        assert parse_date("1990-01-15T00:00:00+03:00") == expected
        assert parse_date(None) is None
        assert parse_date("not-a-date") is None


def test_incremental_sync_backfills_and_updates_birth_dates():
    guests = [
        {"guest_id": 1, "birthday": "1990-01-15 00:00:00", "date_insert": "2020-01-01 00:00:00"},
        {"guest_id": 2, "birthday": "1991-02-16 00:00:00", "date_insert": "2020-01-01 00:00:00"},
        {"guest_id": 3, "birthday": None, "date_insert": "2020-01-01 00:00:00"},
    ]
    existing = {
        1: None,
        2: datetime(1991, 2, 16),
        3: None,
    }

    assert filter_changed_guests(guests, existing) == [guests[0]]
