from scripts import sync_guests, sync_sessions_initial


def test_sessions_initial_reports_page_progress(monkeypatch):
    progress_messages = []

    monkeypatch.setattr(
        sync_sessions_initial,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "api", "secret": "secret", "service_enabled": 1},
    )
    monkeypatch.setattr(sync_sessions_initial, "get_existing_guest_ids", lambda club_id: {1, 2})
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

    result = sync_guests.sync_guests(1, progress=progress_messages.append)

    assert result["received"] == 1
    assert any("страница 1/1" in message for message in progress_messages)
    assert progress_messages[-1].startswith("Гости: готово")
