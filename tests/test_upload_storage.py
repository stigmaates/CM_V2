import importlib

import pytest


def _reload_upload_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("CLUBMODULE_UPLOAD_ROOT", str(tmp_path))
    monkeypatch.setenv("CLUBMODULE_UPLOAD_URL_PREFIX", "/uploads")

    import app.config as config
    import app.services.upload_storage as upload_storage

    importlib.reload(config)
    return importlib.reload(upload_storage)


def test_external_image_url_accepts_https(monkeypatch, tmp_path):
    upload_storage = _reload_upload_storage(monkeypatch, tmp_path)

    assert upload_storage.validate_external_image_url("https://example.com/a.webp") == "https://example.com/a.webp"


def test_external_image_url_rejects_javascript(monkeypatch, tmp_path):
    upload_storage = _reload_upload_storage(monkeypatch, tmp_path)

    with pytest.raises(upload_storage.UploadError):
        upload_storage.validate_external_image_url("javascript:alert(1)")


def test_local_upload_url_cannot_escape_root(monkeypatch, tmp_path):
    upload_storage = _reload_upload_storage(monkeypatch, tmp_path)

    assert upload_storage.get_local_upload_size("/uploads/../secret.webp") == 0
    assert upload_storage.delete_local_upload("/uploads/../secret.webp") is False
