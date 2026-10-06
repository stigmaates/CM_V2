"""Club creation and protected onboarding request are submitted together."""

import json

import pytest

from app.integrations import gizmo_onboarding as onboarding
from app.integrations.gizmo_sync import private_json
from app.main import app
from app.routes.admin import clubs
from tests.test_gizmo_onboarding import certificate as certificate
from tests.test_gizmo_store import Connection


class CreateConnection(Connection):
    def __init__(self):
        super().__init__()
        for column in ("name", "timezone", "lg_api_key", "secret", "owner_id"):
            self.db.execute(f"ALTER TABLE clubs ADD COLUMN {column} TEXT")
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def creation(tmp_path, monkeypatch):
    conn = CreateConnection()
    monkeypatch.setattr(clubs, "get_db_connection", lambda: conn)
    monkeypatch.setattr(clubs, "gizmo_available", lambda: True)
    monkeypatch.setattr(clubs, "_column_exists", lambda *a: True)
    monkeypatch.setattr(onboarding, "require_gizmo_environment", lambda **kw: None)
    monkeypatch.setattr(
        clubs,
        "initial_setup",
        lambda club_id, credentials: onboarding.initial_setup(club_id, credentials, directory=tmp_path),
    )
    return conn, tmp_path


def data(certificate):
    return dict(
        name="New Gizmo",
        integration_provider="gizmo",
        timezone="Asia/Yekaterinburg",
        address="192.0.2.10",
        port="443",
        server_name="gizmo.local",
        gizmo_api_key="gizmo-private-key",
    )


def post(payload):
    with app.test_request_context("/admin/clubs/create", method="POST", data=payload):
        return clubs.create_club.__wrapped__()


def test_gizmo_creation_stores_credentials_and_queues_initial_import(creation, certificate):
    conn, directory = creation
    payload = data(certificate)
    payload.update(api_key="wrong-langame-key", secret="wrong-langame-tenant")
    response = post(payload)
    assert response.status_code == 302
    assert response.location.endswith("/admin/clubs/900002/gizmo")
    club = conn.records("clubs")[-1]
    assert club["name"] == "New Gizmo" and club["integration_provider"] == "gizmo"
    assert club["lg_api_key"] == club["secret"] == ""
    assert club["timezone"] == "Asia/Yekaterinburg" and club["service_enabled"] == 0
    credentials = private_json(directory / "sync-900002.json")
    assert credentials["api_key"] == "gizmo-private-key" and credentials["enabled"] is True
    assert credentials["requested_at_utc"]
    assert private_json(directory / "status-900002.json")["status"] == "queued"
    assert "gizmo-private-key" not in json.dumps(conn.records("club_integrations"))


@pytest.mark.parametrize("invalid", ["address", "gizmo_api_key"])
def test_invalid_gizmo_input_does_not_create_club_and_keeps_nonsecret_fields(creation, certificate, invalid):
    conn, directory = creation
    payload = data(certificate)
    payload.pop(invalid)
    html, status = post(payload)
    assert status == 400
    assert len(conn.records("clubs")) == 1
    assert not list(directory.glob("sync-*.json"))
    assert 'value="New Gizmo"' in html
    assert 'value="gizmo" selected' in html
    assert "gizmo-private-key" not in html


def test_failed_sql_creation_removes_only_its_new_credentials(creation, certificate):
    conn, directory = creation
    onboarding.atomic_json(directory / "sync-900001.json", {"api_key": "existing-secret"})
    conn.db.execute(
        "CREATE TRIGGER fail_create BEFORE INSERT ON clubs BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    html, status = post(data(certificate))
    assert status == 500
    assert len(conn.records("clubs")) == len(conn.records("club_integrations")) == 1
    assert not (directory / "sync-900002.json").exists()
    assert not (directory / "status-900002.json").exists()
    assert private_json(directory / "sync-900001.json")["api_key"] == "existing-secret"
    assert "gizmo-private-key" not in html


def test_credential_write_failure_does_not_create_empty_club(creation, certificate, monkeypatch):
    conn, directory = creation
    atomic = onboarding.atomic_json

    def fail_secret(path, value):
        if path.name.startswith("sync-"):
            raise OSError("disk full")
        atomic(path, value)

    monkeypatch.setattr(onboarding, "atomic_json", fail_secret)
    html, status = post(data(certificate))
    assert status == 400
    assert len(conn.records("clubs")) == 1
    assert not (directory / "status-900002.json").exists()
    assert not (directory / "sync-900002.json").exists()


def test_existing_credentials_are_never_overwritten_by_new_creation(creation, certificate):
    conn, directory = creation
    onboarding.atomic_json(directory / "sync-900002.json", {"api_key": "existing-secret"})
    _, status = post(data(certificate))
    assert status == 400
    assert len(conn.records("clubs")) == 1
    assert private_json(directory / "sync-900002.json")["api_key"] == "existing-secret"


def test_langame_creation_does_not_require_gizmo_fields_or_queue_job(creation):
    conn, directory = creation
    response = post(
        dict(name="LG", integration_provider="langame", timezone="Europe/Moscow", api_key="lg-key", secret="tenant")
    )
    assert response.status_code == 302 and response.location == "/admin/clubs"
    club = conn.records("clubs")[-1]
    assert club["lg_api_key"] == "lg-key" and club["secret"] == "tenant"
    assert list(directory.iterdir()) == []


def test_gizmo_create_not_available_outside_stage(creation, certificate, monkeypatch):
    conn, directory = creation
    monkeypatch.setattr(clubs, "gizmo_available", lambda: False)
    _, status = post(data(certificate))
    assert status == 400 and len(conn.records("clubs")) == 1
    assert list(directory.iterdir()) == []
