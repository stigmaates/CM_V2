"""Durable onboarding requests; API secrets never enter HTML or SQL."""

import hashlib
import ssl
from contextlib import contextmanager
from datetime import UTC, datetime

from app.integrations.gizmo import GizmoClient, GizmoError, GizmoHTTPError
from app.integrations.gizmo_certificate import endpoint
from app.integrations.gizmo_import import all_rows, check_target
from app.integrations.gizmo_lifecycle import read_club
from app.integrations.gizmo_runtime import require_gizmo_environment
from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, read_target, run_lock


def prepare_connection(form, *, certificate_pem=None, existing=None):
    existing = existing or {}
    source = existing.get("connection") or {}
    target = endpoint({**source, **form})
    connection = {k: v for k, v in target.items() if k != "port" or v != 443}
    if source and endpoint(source) != target:
        raise GizmoError("У клуба уже есть подключение. Смену сервера нужно проверить отдельно.")
    key = (form.get("api_key") or existing.get("api_key") or "").strip()
    if not key or len(key) > 4096 or any(c in key for c in "\r\n"):
        raise GizmoError("Укажите корректный API-ключ Gizmo.")
    certificate_pem = certificate_pem or existing.get("certificate_pem")
    if not certificate_pem:
        if source.get("fingerprint"):
            raise GizmoError("Сохранённый сертификат отсутствует. Нужна проверка подключения.")
        # Explicit marker: only a brand-new, unpinned connection may bootstrap.
        # The worker freezes the certificate before making any API request.
        return dict(enabled=True, api_key=key, connection=connection, bootstrap_tls=True)
    if (
        len(certificate_pem) > 16384
        or "PRIVATE KEY" in certificate_pem
        or certificate_pem.count("BEGIN CERTIFICATE") != 1
    ):
        raise GizmoError("Нужен один публичный сертификат сервера, без закрытого ключа.")
    try:
        der = ssl.PEM_cert_to_DER_cert(certificate_pem)
    except ValueError:
        raise GizmoError("Не удалось прочитать сертификат PEM.") from None
    fingerprint = hashlib.sha256(der).hexdigest()
    connection["fingerprint"] = ":".join(fingerprint[i : i + 2] for i in range(0, 64, 2)).upper()
    GizmoClient(**connection, certificate_pem=certificate_pem, api_key=key)
    return dict(enabled=True, api_key=key, certificate_pem=certificate_pem, connection=connection)


@contextmanager
def initial_setup(club_id, credentials, *, directory=DIRECTORY):
    """Hold the import lock until club creation commits; roll back new files on failure."""
    require_gizmo_environment(directory=directory)
    with run_lock(directory / f"sync-{club_id}.lock"):
        paths = [directory / f"status-{club_id}.json", directory / f"sync-{club_id}.json"]
        if any(path.exists() or path.is_symlink() for path in paths):
            raise GizmoError("Для этого ID уже есть подключение Gizmo. Обновите страницу и повторите создание.")
        try:
            atomic_json(paths[0], dict(club_id=club_id, status="queued", phase="queued"))
            atomic_json(paths[1], dict(credentials, requested_at_utc=datetime.now(UTC).isoformat()))
            yield
        except BaseException:
            for path in paths:
                path.unlink(missing_ok=True)
            raise


def inspect_connection(client):
    version = client.get("system/version")
    if not isinstance(version, str) or not version.startswith("3."):
        raise GizmoError("Поддерживается API Gizmo 3. Версию этого сервера нужно проверить отдельно.")
    branches = all_rows(client, "branches")
    if len(branches) != 1:
        raise GizmoError("Пока поддерживается один филиал на сервере Gizmo. Для сети нужна отдельная настройка.")
    methods = all_rows(client, "paymentmethods")
    available = {int(row["id"]) for row in methods}
    if not {-1, -2}.issubset(available):
        raise GizmoError("Не найдены стандартные способы оплаты: наличные и банковские карты.")
    return {"branch_id": int(branches[0]["id"]), "cash_method_ids": [-1, -2], "api_version": version}


def queue_setup(conn, club_id, form, *, certificate_pem=None, directory=DIRECTORY):
    require_gizmo_environment(directory=directory)
    with run_lock(directory / f"sync-{club_id}.lock"):
        settings = read_target(conn, club_id, allow_initial=True, lifecycle=True)
        path = directory / f"sync-{club_id}.json"
        existing = private_json(path) if path.exists() else {}
        existing = dict(existing)
        existing.setdefault("connection", settings.get("source"))
        if (existing.get("connection") or {}).get("fingerprint") and not existing.get("certificate_pem"):
            existing["certificate_pem"] = (directory / "server.pem").read_text()
        if settings.get("source") and endpoint(form) != endpoint(settings["source"]):
            raise GizmoError("У клуба уже есть история. Смену сервера нужно проверить отдельно.")
        credentials = prepare_connection(form, certificate_pem=certificate_pem, existing=existing)
        # Existing imported identity is immutable: a changed endpoint must not
        # silently mix two clubs' guests or overwrite an external ID namespace.
        if settings.get("source") and settings["source"] != credentials["connection"]:
            raise GizmoError("У клуба уже есть история. Смену сервера или сертификата нужно проверить отдельно.")
        club = read_club(conn, club_id)
        credentials["refresh_disabled"] = bool(club.get("integration_ready") and not club.get("service_enabled"))
        credentials["requested_at_utc"] = datetime.now(UTC).isoformat()
        status_path = directory / f"status-{club_id}.json"
        previous = private_json(status_path) if status_path.exists() else {}
        # Write request last. If interrupted, the scheduler cannot consume a new
        # key while an old 'complete' status still hides the queued request.
        atomic_json(
            status_path,
            dict(previous, club_id=club_id, status="queued", phase="queued", error=None, error_message=None),
        )
        atomic_json(path, credentials)


def pause_sync(conn, club_id, *, directory=DIRECTORY):
    require_gizmo_environment(directory=directory)
    with run_lock(directory / f"sync-{club_id}.lock"):
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clubs WHERE club_id=%s", (club_id,))
            check_target(cur.fetchone(), lifecycle=True)
        conn.rollback()
        path = directory / f"sync-{club_id}.json"
        data = private_json(path)
        data["enabled"] = False
        atomic_json(path, data)


def public_connection(club_id, *, directory=DIRECTORY):
    path = directory / f"sync-{club_id}.json"
    credentials = private_json(path) if path.exists() else {}
    source = credentials.get("connection") or {}
    return {key: source[key] for key in ("address", "server_name", "port") if key in source}


def public_status(club_id, *, directory=DIRECTORY):
    status_path = directory / f"status-{club_id}.json"
    state = private_json(status_path) if status_path.exists() else {}
    path = directory / f"sync-{club_id}.json"
    credentials = private_json(path) if path.exists() else {}
    # Whitelist fields: raw settings, keys, rejected guest IDs and certificates
    # are not returned by this endpoint.
    result = {
        key: state.get(key)
        for key in (
            "status",
            "phase",
            "started_at_utc",
            "last_success_at_utc",
            "counts",
            "progress",
            "error_message",
        )
    }
    result["status"] = result["status"] or "unconfigured"
    if credentials and not credentials.get("enabled"):
        result["status"] = "paused"
    result["configured"] = bool(credentials.get("api_key"))
    return result


def public_error(exc):
    if isinstance(exc, GizmoHTTPError):
        if exc.status == 401:
            return "Gizmo отклонил API-ключ. Проверьте ключ и сохраните подключение заново."
        if exc.status == 403:
            return "Недостаточно прав API-ключа Gizmo. Проверьте доступ к данным клуба."
        return f"Gizmo вернул HTTP {exc.status}. Повторите попытку позже."
    if isinstance(exc, ssl.SSLError):
        return "Не прошла проверка HTTPS. Проверьте имя сервера, сертификат и срок его действия."
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "Нет соединения с Gizmo. Проверьте адрес, порт и доступ с сервера Cyber Bonus."
    if isinstance(exc, GizmoError):
        # Only our own validation messages; never include arbitrary driver errors.
        if "already running" in str(exc):
            return "Сейчас идёт обновление. Дождитесь его завершения и повторите действие."
        return str(exc)
    return "Не удалось завершить обновление. Подробности доступны в журнале задач."
