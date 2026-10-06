"""TLS discovery validates names, dates and consistency without API credentials."""

import ssl

import pytest

from app.integrations import gizmo_certificate as cert
from app.integrations.gizmo import GizmoError
from tests.test_gizmo_onboarding import certificate as certificate

TARGET = dict(address="192.0.2.10", port=443, server_name="gizmo.local")


def verification_error(code):
    error = ssl.SSLCertVerificationError("verification failed")
    error.verify_code = code
    return error


@pytest.mark.parametrize("trusted", [True, False])
def test_discovery_checks_name_and_pinned_certificate(monkeypatch, certificate, trusted):
    contexts = []
    der = ssl.PEM_cert_to_DER_cert(certificate)

    def read(target, context):
        assert target == TARGET and "api_key" not in target
        contexts.append(context)
        if not trusted and len(contexts) == 1:
            raise verification_error(18)
        return der

    monkeypatch.setattr(cert, "_certificate", read)
    result = cert.discover(TARGET)
    assert result == dict(certificate_pem=certificate, trusted=trusted)
    assert contexts[-1].check_hostname and contexts[-1].verify_mode == ssl.CERT_REQUIRED
    assert contexts[-1].verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert len(contexts) == (2 if trusted else 3)


@pytest.mark.parametrize("code", [10, 62])
def test_expiry_and_name_mismatch_are_not_downgraded(monkeypatch, code):
    calls = []

    def read(*args):
        calls.append(args)
        raise verification_error(code)

    monkeypatch.setattr(cert, "_certificate", read)
    with pytest.raises(ssl.SSLCertVerificationError):
        cert.discover(TARGET)
    assert len(calls) == 1


def test_changing_certificate_during_probe_rejected(monkeypatch, certificate):
    responses = iter([ssl.PEM_cert_to_DER_cert(certificate), b"changed"])
    monkeypatch.setattr(cert, "_certificate", lambda *a: next(responses))
    with pytest.raises(GizmoError, match="изменился"):
        cert.discover(TARGET)
