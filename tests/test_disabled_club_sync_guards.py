def _fail_fetch(*args, **kwargs):
    raise AssertionError("disabled club should not call external API")


def test_guests_initial_skips_disabled_club(monkeypatch):
    from scripts import sync_guests

    monkeypatch.setattr(
        sync_guests,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "key", "secret": "secret", "service_enabled": 0},
    )
    monkeypatch.setattr(sync_guests, "fetch_guests", _fail_fetch)

    result = sync_guests.sync_guests(2)

    assert result["status"] == "skipped_disabled"


def test_sessions_initial_skips_disabled_club(monkeypatch):
    from scripts import sync_sessions_initial

    monkeypatch.setattr(
        sync_sessions_initial,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "key", "secret": "secret", "service_enabled": 0},
    )
    monkeypatch.setattr(sync_sessions_initial, "fetch_sessions_page", _fail_fetch)

    result = sync_sessions_initial.sync_sessions_initial(2)

    assert result["status"] == "skipped_disabled"


def test_operations_initial_skips_disabled_club(monkeypatch):
    from scripts import sync_operations_initial

    monkeypatch.setattr(
        sync_operations_initial,
        "get_club_data",
        lambda club_id: {"club_id": club_id, "lg_api_key": "key", "secret": "secret", "service_enabled": 0},
    )
    monkeypatch.setattr(sync_operations_initial, "fetch_operations", _fail_fetch)

    result = sync_operations_initial.sync_operations_initial(2, date_from="2026-01-01", date_to="2026-01-02")

    assert result["status"] == "skipped_disabled"


def test_balance_topups_initial_skips_disabled_club(monkeypatch):
    from scripts import sync_balance_topups_initial

    monkeypatch.setattr(
        sync_balance_topups_initial,
        "get_clubs",
        lambda club_id=None: [{"club_id": club_id or 2, "lg_api_key": "key", "secret": "secret", "service_enabled": 0}],
    )
    monkeypatch.setattr(sync_balance_topups_initial, "fetch_topups", _fail_fetch)

    result = sync_balance_topups_initial.sync_balance_topups_initial(2, date_from="2026-01-01", date_to="2026-01-02")

    assert result["status"] == "skipped_disabled"
