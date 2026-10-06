"""Gizmo v3 read-only HTTPS client. No application or database imports."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlencode


class GizmoError(ValueError):
    pass


class GizmoHTTPError(GizmoError):
    def __init__(self, resource, status):
        self.status = status
        super().__init__(f"Gizmo {resource}: HTTP {status}")


class GizmoClient:
    def __init__(self, *, address, server_name, certificate_pem, fingerprint, api_key, port=443):
        ipaddress.ip_address(address)
        self.address, self.server_name, self.port = address, server_name, int(port)
        if not server_name or any(c in server_name for c in "/\\\r\n :"):
            raise GizmoError("Invalid Gizmo TLS server name")
        self.fingerprint = fingerprint.replace(":", "").lower()
        if len(self.fingerprint) != 64 or any(c not in "0123456789abcdef" for c in self.fingerprint):
            raise GizmoError("Invalid SHA256 fingerprint")
        self.api_key = api_key.strip()
        if not self.api_key or any(c in self.api_key for c in "\r\n"):
            raise GizmoError("Empty or invalid API key")
        der = ssl.PEM_cert_to_DER_cert(certificate_pem)
        if hashlib.sha256(der).hexdigest() != self.fingerprint:
            raise GizmoError("Certificate does not match the approved fingerprint")
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.load_verify_locations(cadata=certificate_pem)

    def get(self, resource, params=None):
        # Only GETs are retried. Authentication, TLS and malformed data require
        # attention and must not trigger repeated requests with the same key.
        for attempt in range(3):
            try:
                return self._get_once(resource, params)
            except GizmoHTTPError as exc:
                if exc.status not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
            except ssl.SSLError:
                raise
            except (TimeoutError, ConnectionError, http.client.RemoteDisconnected, http.client.IncompleteRead):
                if attempt == 2:
                    raise
            time.sleep(2**attempt)

    def _get_once(self, resource, params=None):
        if not resource or resource.startswith("/") or any(c in resource for c in "?#\r\n") or ".." in resource:
            raise GizmoError("Invalid API resource")
        client = self

        class Connection(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((client.address, client.port), timeout=self.timeout)
                try:
                    self.sock = client.context.wrap_socket(raw, server_hostname=client.server_name)
                    if hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest() != client.fingerprint:
                        self.sock.close()
                        raise GizmoError("Server certificate changed")
                except BaseException:
                    raw.close()
                    raise

        conn = Connection(self.server_name, self.port, timeout=30, context=self.context)
        try:
            path = "/api/v3/" + resource
            if params:
                path += "?" + urlencode(params)
            conn.request("GET", path, headers={"Accept": "application/json", "X-API-KEY": self.api_key})
            response = conn.getresponse()
            if response.status != 200:
                raise GizmoHTTPError(resource, response.status)
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise GizmoError("Response too large; use a smaller time window")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise GizmoError("Gizmo returned invalid JSON") from None
            if not isinstance(payload, dict) or "result" not in payload:
                raise GizmoError("Unexpected Gizmo response envelope")
            if payload.get("isError") is not False or payload.get("httpStatusCode") != 200:
                raise GizmoError("Gizmo returned an application error")
            return payload["result"]
        finally:
            conn.close()


def page_rows(result):
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise GizmoError("Expected a Gizmo paginated data array")
    return result["data"]


def iter_pages(client, resource, params=None, *, limit=100, max_pages=1000):
    """Never silently import only the first page or guess an opaque cursor encoding."""
    query = dict(params or {}, **{"Pagination.Limit": limit})
    seen = set()
    for _ in range(max_pages):
        result = client.get(resource, query)
        rows = page_rows(result)
        yield rows
        cursor = result.get("nextCursor")
        if cursor is None:
            return
        if not isinstance(cursor, str) or not cursor:
            raise GizmoError("Object cursor encoding needs verification against this Gizmo build")
        if cursor in seen or not rows:
            raise GizmoError("Gizmo pagination did not advance")
        seen.add(cursor)
        query["Pagination.Cursor"] = cursor
    raise GizmoError("Gizmo pagination exceeded safety limit")
