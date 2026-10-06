"""Credential-free TLS discovery for first-use pinning in the background worker."""

import ipaddress
import socket
import ssl

from app.integrations.gizmo import GizmoError


def endpoint(form):
    try:
        address = str(ipaddress.ip_address((form.get("address") or "").strip()))
        port = int(form.get("port") or 443)
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise GizmoError("Укажите IP-адрес Gizmo и порт от 1 до 65535.") from None
    name = (form.get("server_name") or "gizmo.local").strip()
    if not name or any(c in name for c in "/\\\r\n :"):
        raise GizmoError("Проверьте имя сервера в сертификате.")
    return dict(address=address, port=port, server_name=name)


def _certificate(target, context):
    # No HTTP request and no credentials: this connection reads only public TLS metadata.
    with socket.create_connection((target["address"], target["port"]), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=target["server_name"]) as tls:
            return tls.getpeercert(binary_form=True)


def discover(target):
    trusted = True
    try:
        der = _certificate(target, ssl.create_default_context())
    except ssl.SSLCertVerificationError as exc:
        # Only unknown issuer errors permit first-use pinning. Expiry / name mismatch
        # are not bypassed, including on the subsequent pinned handshake.
        if exc.verify_code not in {18, 19, 20, 21}:
            raise
        trusted = False
        untrusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        untrusted.check_hostname = False
        untrusted.verify_mode = ssl.CERT_NONE
        der = _certificate(target, untrusted)
    pem = ssl.DER_cert_to_PEM_cert(der)
    pinned = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    pinned.load_verify_locations(cadata=pem)
    pinned.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    if _certificate(target, pinned) != der:
        raise GizmoError("Сертификат изменился во время проверки. Повторите получение.")
    return dict(certificate_pem=pem, trusted=trusted)
