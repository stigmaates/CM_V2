"""A new empty club can queue a durable import without a per-club SSH script."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.integrations import gizmo_onboarding as onboarding
from app.integrations import gizmo_sync as sync
from app.integrations.gizmo import GizmoError, GizmoHTTPError
from app.main import app
from app.routes.admin import gizmo as routes
from tests.test_gizmo_history_references import HistoryAPI
from tests.test_gizmo_store import Connection


@pytest.fixture(scope="module")
def certificate():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gizmo.local")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("gizmo.local")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture
def setup(tmp_path, monkeypatch, certificate):
    monkeypatch.setattr(onboarding, "require_gizmo_environment", lambda **kw: None)
    monkeypatch.setattr(sync, "require_gizmo_environment", lambda **kw: None)
    monkeypatch.setattr(sync, "start_job_run", lambda *a, **kw: 1)
    monkeypatch.setattr(sync, "finish_job_run", lambda *a, **kw: None)
    monkeypatch.setattr(sync, "rebuild_club_portrait", lambda *a: {"status": "updated", "guests": 1})
    monkeypatch.setattr(sync, "refresh_club", lambda *a, **kw: {"status": "updated", "guests": 1})
    conn = Connection()
    form = dict(address="192.0.2.10", server_name="gizmo.local", api_key="secret-test-key", port="443")
    return conn, form, tmp_path


def queued(setup, certificate):
    conn, form, directory = setup
    onboarding.queue_setup(conn, 900001, form, certificate_pem=certificate, directory=directory)
    return conn, directory


def api(monkeypatch):
    source = HistoryAPI()
    source.details["system/version"] = "3.0.92"
    source.data["paymentmethods"].append({"id": -2})
    monkeypatch.setattr(sync, "GizmoClient", lambda **kw: source)
    return source


def test_first_connection_imports_common_tables_and_repeats_without_duplicates(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    assert conn.records("club_integrations")[0]["settings"] is None  # queue does not invent a verified mapping
    assert conn.records("guests") == []
    api(monkeypatch)
    status = sync.synchronize(conn, 900001, directory=directory, only_if_due=True)
    assert status["status"] == "complete"
    assert status["progress"]["resource"] == "usersessions"
    assert len(conn.records("guest_sessions")) == len(conn.records("guests")) == 1
    settings = json.loads(conn.records("club_integrations")[0]["settings"])
    assert settings["branch_id"] == 1
    assert settings["session_source"] == "sessions+usersessions:same-id-user-span:v1"
    assert "secret-test-key" not in json.dumps(settings)
    assert "requested_at_utc" not in sync.private_json(directory / "sync-900001.json")
    assert sync.synchronize(conn, 900001, directory=directory, only_if_due=True)["status"] == "not_due"
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "complete"
    assert len(conn.records("guest_sessions")) == 1
    assert conn.records("clubs")[0]["service_enabled"] == 0
    assert conn.records("clubs")[0]["integration_ready"] == 0


def test_bad_key_does_not_create_history_and_can_be_corrected(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    source = api(monkeypatch)
    source.details["system/version"] = GizmoHTTPError("system/version", 403)
    with pytest.raises(GizmoHTTPError):
        sync.synchronize(conn, 900001, directory=directory)
    assert conn.records("guests") == []
    state = onboarding.public_status(900001, directory=directory)
    assert "прав" in state["error_message"]
    assert state["status"] == "error"
    assert "secret-test-key" not in json.dumps(state)
    onboarding.queue_setup(conn, 900001, {**setup[1], "api_key": "corrected"}, directory=directory)
    source.details["system/version"] = "3.0.92"
    assert sync.synchronize(conn, 900001, directory=directory, only_if_due=True)["status"] == "complete"


def test_source_mapping_failure_never_partially_writes_initial_import(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    source = api(monkeypatch)
    source.data["usersessions"][0]["span"] = 42
    with pytest.raises(GizmoError, match="duration mismatch"):
        sync.synchronize(conn, 900001, directory=directory)
    assert conn.records("guests") == conn.records("guest_sessions") == []
    assert conn.records("club_integrations")[0]["settings"] is None


def test_queue_refuses_to_replace_existing_imported_identity(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    api(monkeypatch)
    sync.synchronize(conn, 900001, directory=directory)
    previous = (directory / "sync-900001.json").read_bytes()
    with pytest.raises(GizmoError, match="уже есть история"):
        onboarding.queue_setup(conn, 900001, {**setup[1], "address": "192.0.2.11"}, directory=directory)
    assert (directory / "sync-900001.json").read_bytes() == previous


def test_pause_and_resume_preserve_import_and_existing_secret(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    api(monkeypatch)
    sync.synchronize(conn, 900001, directory=directory)
    onboarding.pause_sync(conn, 900001, directory=directory)
    assert onboarding.public_status(900001, directory=directory)["status"] == "paused"
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "paused"
    onboarding.queue_setup(conn, 900001, {**setup[1], "api_key": ""}, directory=directory)
    assert sync.private_json(directory / "sync-900001.json")["api_key"] == "secret-test-key"
    assert sync.synchronize(conn, 900001, directory=directory, only_if_due=True)["status"] == "complete"
    assert len(conn.records("guest_sessions")) == 1


def test_queue_cannot_change_credentials_during_an_import(setup, certificate):
    conn, _, directory = setup
    with sync.run_lock(directory / "sync-900001.lock"):
        with pytest.raises(GizmoError, match="already running"):
            onboarding.queue_setup(conn, 900001, setup[1], certificate_pem=certificate, directory=directory)
    assert not (directory / "sync-900001.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("address", "http://server/path"),
        ("port", "0"),
        ("port", "65536"),
        ("server_name", "gizmo.local\r\nX-Test: 1"),
        ("api_key", "abc\ndef"),
    ],
)
def test_connection_rejects_invalid_endpoint_and_header_injection(certificate, field, value):
    form = dict(address="192.0.2.10", server_name="gizmo.local", api_key="secret")
    with pytest.raises(GizmoError):
        onboarding.prepare_connection({**form, field: value}, certificate_pem=certificate)


def test_certificate_upload_cannot_contain_private_key(certificate):
    with pytest.raises(GizmoError, match="закрытого ключа"):
        onboarding.prepare_connection(
            {"address": "192.0.2.10", "api_key": "secret"}, certificate_pem=certificate + "\nPRIVATE KEY"
        )


@pytest.mark.parametrize("version,branches,match", [("2.0.0", [1], "Gizmo 3"), ("3.0.92", [1, 2], "один филиал")])
def test_incompatible_version_or_multi_branch_is_not_silently_imported(version, branches, match):
    class API:
        def get(self, resource, params=None):
            if resource == "system/version":
                return version
            return dict(data=[{"id": x} for x in branches], nextCursor=None)

    with pytest.raises(GizmoError, match=match):
        onboarding.inspect_connection(API())


def test_owner_cannot_access_admin_gizmo_routes(monkeypatch):
    monkeypatch.setattr(routes, "target", lambda *a: pytest.fail("Non-admin reached setup"))
    with app.test_request_context("/admin/clubs/900001/gizmo/status", headers={"Accept": "application/json"}):
        from flask import session

        session.update(user_id=10, role="owner")
        response, status = routes.gizmo_status(900001)
        assert status == 403


def test_setup_hidden_outside_stage(monkeypatch):
    monkeypatch.setattr(routes, "gizmo_available", lambda: False)
    with app.test_request_context("/admin/clubs/900001/gizmo"):
        from werkzeug.exceptions import NotFound

        with pytest.raises(NotFound):
            routes.target(900001)


def test_status_and_setup_never_render_saved_secrets(setup, certificate, monkeypatch):
    conn, directory = queued(setup, certificate)
    state = onboarding.public_status(900001, directory=directory)
    conn.close = lambda: None
    monkeypatch.setattr(routes, "target", lambda club_id: {"club_id": club_id, "name": "Next"})
    monkeypatch.setattr(routes, "get_db_connection", lambda: conn)
    monkeypatch.setattr(routes, "public_status", lambda club_id: state)
    monkeypatch.setattr(
        routes, "public_connection", lambda club_id: onboarding.public_connection(club_id, directory=directory)
    )
    with app.test_request_context("/admin/clubs/900001/gizmo"):
        page = routes.gizmo_setup.__wrapped__(900001)
    assert "secret-test-key" not in page and "BEGIN CERTIFICATE" not in page
    assert 'value="192.0.2.10"' in page
    assert "Проверить и загрузить данные" in page
    with app.test_request_context("/admin/clubs/900001/gizmo/status"):
        response = routes.gizmo_status.__wrapped__(900001)
        assert response.headers["Cache-Control"] == "no-store"
        assert "secret-test-key" not in response.get_data(as_text=True)


def test_new_connection_pins_in_background_before_key_is_used(setup, certificate, monkeypatch):
    conn, form, directory = setup
    onboarding.queue_setup(conn, 900001, form, directory=directory)
    before = sync.private_json(directory / "sync-900001.json")
    assert before["bootstrap_tls"] and "certificate_pem" not in before
    discoveries = []

    def discover(target):
        discoveries.append(target)
        assert "api_key" not in target
        return dict(certificate_pem=certificate, trusted=False)

    monkeypatch.setattr(sync, "discover", discover)
    source = api(monkeypatch)

    def client(**kwargs):
        saved = sync.private_json(directory / "sync-900001.json")
        assert saved["certificate_pem"] == certificate
        assert saved["connection"]["fingerprint"] == kwargs["fingerprint"]
        assert "bootstrap_tls" not in saved
        return source

    monkeypatch.setattr(sync, "GizmoClient", client)
    source.details["system/version"] = GizmoHTTPError("system/version", 403)
    with pytest.raises(GizmoHTTPError):
        sync.synchronize(conn, 900001, directory=directory)
    assert len(discoveries) == 1
    assert conn.records("guests") == []
    onboarding.queue_setup(conn, 900001, dict(form, api_key="corrected"), directory=directory)
    source.details["system/version"] = "3.0.92"
    assert sync.synchronize(conn, 900001, directory=directory)["status"] == "complete"
    assert len(discoveries) == 1  # Retry cannot replace the initially pinned identity.
    assert len(conn.records("guests")) == 1


def test_failed_pin_write_never_sends_api_key(setup, certificate, monkeypatch):
    conn, form, directory = setup
    onboarding.queue_setup(conn, 900001, form, directory=directory)
    monkeypatch.setattr(sync, "discover", lambda target: dict(certificate_pem=certificate, trusted=False))
    original = sync.atomic_json

    def fail_pin(path, value):
        if path.name == "sync-900001.json":
            raise OSError("disk full")
        original(path, value)

    monkeypatch.setattr(sync, "atomic_json", fail_pin)
    monkeypatch.setattr(sync, "GizmoClient", lambda **kw: pytest.fail("API client used before pin was saved"))
    with pytest.raises(OSError):
        sync.synchronize(conn, 900001, directory=directory)
    assert conn.records("guests") == []
