from datetime import datetime, timedelta

import pytest

from scripts import process_auto_mailings


@pytest.mark.parametrize(
    ("local_now", "expected"),
    [
        (datetime(2026, 8, 25, 9, 59), False),
        (datetime(2026, 8, 25, 10, 0), True),
        (datetime(2026, 8, 25, 22, 29, 59), True),
        (datetime(2026, 8, 25, 22, 30), False),
    ],
)
def test_auto_mailing_send_window_boundaries(local_now, expected):
    assert (
        process_auto_mailings._is_auto_mailing_send_window(
            "Asia/Yekaterinburg",
            now=local_now,
        )
        is expected
    )


def test_auto_mailing_window_requests_club_timezone(monkeypatch):
    seen = []

    def fake_now(timezone_name):
        seen.append(timezone_name)
        return datetime(2026, 8, 25, 12, 0)

    monkeypatch.setattr(process_auto_mailings, "_get_auto_mailing_now", fake_now)

    assert process_auto_mailings._is_auto_mailing_send_window("Asia/Yekaterinburg") is True
    assert seen == ["Asia/Yekaterinburg"]


@pytest.mark.parametrize(
    ("local_now", "start", "end", "expected"),
    [
        (datetime(2026, 8, 25, 8, 59), "09:00", "18:00", False),
        (datetime(2026, 8, 25, 9, 0), "09:00", "18:00", True),
        (datetime(2026, 8, 25, 17, 59), "09:00", "18:00", True),
        (datetime(2026, 8, 25, 18, 0), "09:00", "18:00", False),
        (datetime(2026, 8, 25, 23, 30), "22:00", "02:00", True),
        (datetime(2026, 8, 25, 1, 59), "22:00", "02:00", True),
        (datetime(2026, 8, 25, 2, 0), "22:00", "02:00", False),
        (datetime(2026, 8, 25, 12, 0), "22:00", "02:00", False),
        (datetime(2026, 8, 25, 12, 0), timedelta(hours=10), timedelta(hours=22, minutes=30), True),
    ],
)
def test_auto_mailing_uses_configured_window_including_overnight(local_now, start, end, expected):
    assert (
        process_auto_mailings._is_auto_mailing_send_window(
            "Europe/Moscow",
            start,
            end,
            now=local_now,
        )
        is expected
    )


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_processor_skips_every_auto_mailing_type_outside_window(monkeypatch):
    rows = [
        {
            "id": index,
            "club_id": 7,
            "code": code,
            "club_timezone": "Asia/Yekaterinburg",
        }
        for index, code in enumerate(
            ("inactive_14_bonus", "first_visit_survey", "streak_expiring_reminder"),
            start=1,
        )
    ]
    conn = _Connection(rows)
    monkeypatch.setattr(process_auto_mailings, "get_db_connection", lambda: conn)
    checked_windows = []

    def outside_window(timezone_name, send_start_time, send_end_time):
        checked_windows.append((timezone_name, send_start_time, send_end_time))
        return False

    monkeypatch.setattr(process_auto_mailings, "_is_auto_mailing_send_window", outside_window)

    def unexpected_process(*args, **kwargs):
        raise AssertionError("Авторассылка не должна обрабатываться вне окна")

    monkeypatch.setattr(process_auto_mailings, "process_inactive_14_bonus", unexpected_process)
    monkeypatch.setattr(process_auto_mailings, "process_first_visit_survey", unexpected_process)
    monkeypatch.setattr(process_auto_mailings, "process_streak_expiring_reminder", unexpected_process)

    result = process_auto_mailings.process_auto_mailings()

    assert result == {"processed": [], "recipients_created": 0}
    assert checked_windows == [("Asia/Yekaterinburg", None, None)] * 3
    assert "c.timezone" in conn.cursor_obj.query
    assert conn.closed is True
