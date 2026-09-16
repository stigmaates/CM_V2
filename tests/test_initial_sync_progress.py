from scripts import sync_guests, sync_sessions_incremental, sync_sessions_initial


class _Lock:
    acquired = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_sessions_initial_reports_page_progress(monkeypatch):
    progress_messages = []

    monkeypatch.setattr(
        sync_sessions_initial,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "api", "secret": "secret", "service_enabled": 1},
    )
    monkeypatch.setattr(
        sync_sessions_initial,
        "fetch_sessions_page",
        lambda secret, api_key, page: {
            "status": True,
            "total_pages": 2,
            "data": [{"id": page, "guest_id": 1, "UUID": "x", "date_start": None, "date_stop": None}],
        },
    )
    monkeypatch.setattr(sync_sessions_initial, "save_sessions", lambda club_id, sessions: len(sessions))

    result = sync_sessions_initial.sync_sessions_initial(1, progress=progress_messages.append)

    assert result["saved"] == 2
    assert any("страница 1/2" in message for message in progress_messages)
    assert any("страница 2/2" in message for message in progress_messages)
    assert progress_messages[-1].startswith("Сессии: готово")


def test_sessions_initial_matches_string_api_guest_ids_to_integer_database_ids():
    sessions = [
        {"id": 10, "guest_id": "1"},
        {"id": 11, "guest_id": 2},
        {"id": 12, "guest_id": "999"},
        {"id": 13, "guest_id": None},
    ]

    filtered, skipped = sync_sessions_initial.filter_sessions(sessions)

    assert [row["id"] for row in filtered] == [10, 11, 12]
    assert [row["guest_id"] for row in filtered] == [1, 2, 999]
    assert skipped == 1


def test_sessions_incremental_keeps_orphans_for_utilization_after_normalizing_guest_ids(monkeypatch):
    saved_rows = []
    finished = []
    monkeypatch.setattr(
        sync_sessions_incremental,
        "get_clubs",
        lambda club_id=None: [{"club_id": 4, "lg_api_key": "key", "secret": "club", "service_enabled": 1}],
    )
    monkeypatch.setattr(sync_sessions_incremental, "job_lock", lambda *args, **kwargs: _Lock())
    monkeypatch.setattr(sync_sessions_incremental, "start_job_run", lambda *args, **kwargs: 10)
    monkeypatch.setattr(
        sync_sessions_incremental,
        "finish_job_run",
        lambda job_id, status, **kwargs: finished.append((status, kwargs)),
    )
    monkeypatch.setattr(
        sync_sessions_incremental,
        "fetch_sessions",
        lambda *args, **kwargs: {
            "status": True,
            "total_pages": 1,
            "data": [{"id": 1, "guest_id": "100"}, {"id": 2, "guest_id": "999"}],
        },
    )
    monkeypatch.setattr(
        sync_sessions_incremental,
        "save_sessions",
        lambda club_id, rows: saved_rows.extend(rows) or len(rows),
    )

    result = sync_sessions_incremental.sync_sessions_incremental(4)

    assert [row["guest_id"] for row in saved_rows] == [100, 999]
    assert result[0]["received"] == 2
    assert result[0]["saved"] == 2
    assert result[0]["skipped"] == 0
    assert finished[-1][0] == "success"
    assert finished[-1][1]["metadata"]["rows_skipped"] == 0


def test_guests_initial_reports_page_progress(monkeypatch):
    progress_messages = []

    monkeypatch.setattr(
        sync_guests,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "api", "secret": "secret", "service_enabled": 1},
    )
    monkeypatch.setattr(
        sync_guests,
        "fetch_guests",
        lambda secret, api_key, progress=None: [
            progress("Гости: загружена страница 1/1. Получено на странице: 1") or {"guest_id": 1}
        ],
    )
    monkeypatch.setattr(sync_guests, "save_guests", lambda club_id, guests: None)
    monkeypatch.setattr(sync_guests, "record_cooperation_start", lambda club_id, started_at: None)

    result = sync_guests.sync_guests(1, progress=progress_messages.append)

    assert result["received"] == 1
    assert any("страница 1/1" in message for message in progress_messages)
    assert progress_messages[-1].startswith("Гости: готово")
