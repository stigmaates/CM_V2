import multiprocessing
import ssl
import time

import pytest
from flask import Flask

from app.core import admin_required, create_flask_app
from app.database_transport import database_ssl
from app.services.login_throttle import login_is_limited
from app.services.rate_limit import client_ip


def test_changed_password_revokes_previously_valid_cookie(staff_login):
    app = create_flask_app()

    @app.get("/admin/probe")
    @admin_required
    def probe():
        return "ok"

    client = app.test_client()
    user = staff_login(client, role="admin")
    assert client.get("/admin/probe").status_code == 200
    user["pass_hash"] = "new-password-hash"
    assert client.get("/admin/probe", headers={"Accept": "application/json"}).status_code == 401


@pytest.mark.parametrize("change", ["role", "club_id", "expired", "missing_stamp"])
def test_authority_or_lifetime_change_revokes_login(staff_login, change):
    app = create_flask_app()

    @app.get("/admin/probe")
    def probe():
        return "ok"

    client = app.test_client()
    user = staff_login(client, role="admin")
    if change in ("role", "club_id"):
        user[change] = "changed"
    else:
        with client.session_transaction() as session:
            if change == "expired":
                session["_staff_login_at"] = time.time() - 13 * 3600
            else:
                session.pop("_staff_authority")
    assert client.get("/admin/probe").status_code == 302


def test_lookup_failure_fails_closed_without_exception_details(staff_login, monkeypatch):
    from app.services import staff_sessions

    app = create_flask_app()

    @app.get("/admin/probe")
    def probe():
        return "ok"

    client = app.test_client()
    staff_login(client, role="admin")

    def failed(_):
        raise RuntimeError("sensitive-database-detail")

    monkeypatch.setattr(staff_sessions, "load_staff_user", failed)
    response = client.get("/admin/probe")
    assert response.status_code == 503
    assert b"sensitive" not in response.data


def test_admin_impersonation_keeps_actor_authority(staff_login):
    app = create_flask_app()

    @app.get("/admin/probe")
    def probe():
        return "ok"

    client = app.test_client()
    staff_login(client, role="admin", club_id=None)
    with client.session_transaction() as session:
        session.update(club_id=5, impersonating_owner=True, impersonated_club_id=5)
    assert client.get("/admin/probe").status_code == 200


def test_environment_salts_reject_copied_cookie_even_with_same_key(monkeypatch, staff_login):
    import app.core as core

    monkeypatch.setattr(core, "APP_ENV", "stage")
    stage = core.create_flask_app()
    monkeypatch.setattr(core, "APP_ENV", "production")
    prod = core.create_flask_app()
    stage.secret_key = prod.secret_key = "synthetic-shared-key"

    @prod.get("/admin/probe")
    @admin_required
    def probe():
        return "ok"

    source = stage.test_client()
    staff_login(source, role="admin")
    target = prod.test_client()
    target.set_cookie("session", source.get_cookie("session").value)
    assert target.get("/admin/probe", headers={"Accept": "application/json"}).status_code == 401
    assert stage.config["SESSION_COOKIE_SECURE"] is True


def test_forwarded_list_cannot_change_client_identity():
    app = Flask(__name__)
    for spoofed in ("198.51.100.1", "198.51.100.2"):
        with app.test_request_context(
            "/",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Real-IP": "203.0.113.2", "X-Forwarded-For": spoofed},
        ):
            assert client_ip() == "203.0.113.2"
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.3"}, headers={"X-Real-IP": spoofed}):
            assert client_ip() == "203.0.113.3"


def throttle_worker(path, ip, login, output):
    app = Flask(__name__)
    app.config["LOGIN_RATE_LIMIT_FILE"] = path
    with app.app_context():
        output.put(login_is_limited(ip, login, now=100))


def test_limit_is_shared_between_independent_processes(tmp_path):
    path = str(tmp_path / "limits.sqlite3")
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [context.Process(target=throttle_worker, args=(path, "203.0.113.2", "test", queue)) for _ in range(12)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    results = [queue.get(timeout=5) for _ in processes]
    assert results.count(False) == 10
    assert results.count(True) == 2
    assert (tmp_path / "limits.sqlite3").stat().st_mode & 0o777 == 0o600


def test_account_limit_applies_across_ips_and_expires(tmp_path):
    app = Flask(__name__)
    app.config["LOGIN_RATE_LIMIT_FILE"] = str(tmp_path / "limits.sqlite3")
    with app.app_context():
        assert not any(login_is_limited(f"192.0.2.{i}", "Account", now=100) for i in range(20))
        assert login_is_limited("198.51.100.1", "ACCOUNT", now=101)
        assert not login_is_limited("198.51.100.2", "account", now=1001)


def test_database_requires_valid_certificate_and_hostname():
    context = database_ssl({})
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(OSError):
        database_ssl({"DB_SSL_CA": "/nonexistent/ca.pem"})


def test_stage_mirror_preserves_staff_accounts_and_login_tokens():
    from scripts.mirror_production_to_stage import PRESERVE

    assert {"users", "guest_login_tokens"} <= PRESERVE


def test_fresh_login_clears_prior_authority_and_sets_revocable_stamp(monkeypatch, tmp_path):
    from werkzeug.security import generate_password_hash

    from app.routes.common import auth, auth_bp
    from app.services import staff_sessions

    user = dict(
        user_id=1,
        role="admin",
        club_id=None,
        pass_hash=generate_password_hash("example-good-password"),
        name="Test",
        login="test",
    )

    class Connection:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            pass

        def fetchone(self):
            return user

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(auth, "get_db_connection", Connection)
    monkeypatch.setattr(staff_sessions, "load_staff_user", lambda uid: user)
    app = create_flask_app()
    app.config["LOGIN_RATE_LIMIT_FILE"] = str(tmp_path / "rate.sqlite3")
    app.register_blueprint(auth_bp)
    app.add_url_rule("/admin/probe", endpoint="admin.dashboard", view_func=lambda: "ok")
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(_csrf_token="before-login", impersonating_owner=True, guest_id=999)
    response = client.post(
        "/login", data={"login": "test", "password": "example-good-password", "csrf_token": "before-login"}
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["role"] == "admin"
        assert "_staff_authority" in session
        assert "guest_id" not in session and "impersonating_owner" not in session
        assert "_csrf_token" not in session
    assert client.get("/admin/probe").status_code == 200
    user["pass_hash"] = generate_password_hash("different-good-password")
    assert client.get("/admin/probe").headers["Location"] == "/login"


def test_peer_identity_does_not_require_other_environment_secrets(monkeypatch, tmp_path):
    import json
    import stat
    from types import SimpleNamespace

    from app.integrations import database_identity as identity

    path = tmp_path / "identities.json"
    values = {"DB_HOST": "db.example", "DB_PORT": 3306, "DB_NAME": "production"}
    path.write_text(json.dumps({"production": values}))
    monkeypatch.setattr(identity, "IDENTITIES_FILE", path)
    monkeypatch.setattr(identity.os, "fstat", lambda fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o644))
    monkeypatch.setattr(identity, "dotenv_values", lambda path: pytest.fail("Must not read peer secrets"))
    assert identity.peer_database_identity("production", legacy_env="/unreadable/.env") == values
    monkeypatch.setattr(identity.os, "fstat", lambda fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o666))
    with pytest.raises(ValueError):
        identity.peer_database_identity("production", legacy_env="/unreadable/.env")
