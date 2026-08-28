import pytest

from scripts import sync_operations_incremental


class _AcquiredLock:
    acquired = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _club(club_id):
    return {
        "club_id": club_id,
        "lg_api_key": f"key-{club_id}",
        "secret": f"club-{club_id}",
    }


def test_global_operations_sync_continues_after_one_club_fails(monkeypatch):
    fetched_clubs = []
    finished_runs = []

    monkeypatch.setattr(sync_operations_incremental, "get_clubs", lambda club_id=None: [_club(1), _club(2)])
    monkeypatch.setattr(sync_operations_incremental, "is_service_enabled", lambda club: True)
    monkeypatch.setattr(sync_operations_incremental, "job_lock", lambda *args, **kwargs: _AcquiredLock())
    monkeypatch.setattr(
        sync_operations_incremental,
        "start_job_run",
        lambda job_type, club_id, metadata: club_id,
    )
    monkeypatch.setattr(
        sync_operations_incremental,
        "finish_job_run",
        lambda job_run_id, status, **kwargs: finished_runs.append((job_run_id, status)),
    )

    def fetch_operations(secret, api_key, club_id, date_from, date_to):
        fetched_clubs.append(club_id)
        if club_id == 1:
            raise RuntimeError("Langame unavailable")
        return [{"id": 42}]

    monkeypatch.setattr(sync_operations_incremental, "fetch_operations", fetch_operations)
    monkeypatch.setattr(sync_operations_incremental, "save_operations", lambda club_id, operations: len(operations))

    result = sync_operations_incremental.sync_operations_incremental()

    assert fetched_clubs == [1, 2]
    assert result[0]["club_id"] == 1
    assert result[0]["error"] == "Langame unavailable"
    assert result[1]["club_id"] == 2
    assert result[1]["saved"] == 1
    assert finished_runs == [(1, "error"), (2, "success")]


def test_single_club_operations_sync_still_reports_failure(monkeypatch):
    monkeypatch.setattr(sync_operations_incremental, "get_clubs", lambda club_id=None: [_club(club_id)])
    monkeypatch.setattr(sync_operations_incremental, "is_service_enabled", lambda club: True)
    monkeypatch.setattr(sync_operations_incremental, "job_lock", lambda *args, **kwargs: _AcquiredLock())
    monkeypatch.setattr(sync_operations_incremental, "start_job_run", lambda *args, **kwargs: 2)
    monkeypatch.setattr(sync_operations_incremental, "finish_job_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sync_operations_incremental,
        "fetch_operations",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Langame unavailable")),
    )

    with pytest.raises(RuntimeError, match="Langame unavailable"):
        sync_operations_incremental.sync_operations_incremental(club_id=2)
