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


def test_copy_local_upload_creates_independent_file(monkeypatch, tmp_path):
    upload_storage = _reload_upload_storage(monkeypatch, tmp_path)
    source = tmp_path / "cases" / "1" / "items" / "source.webp"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"webp-content")

    copied_url = upload_storage.copy_local_upload(
        url="/uploads/cases/1/items/source.webp",
        club_id=1,
        kind="case_item",
    )

    assert copied_url != "/uploads/cases/1/items/source.webp"
    copied_path = tmp_path / copied_url.removeprefix("/uploads/")
    assert copied_path.read_bytes() == b"webp-content"
    assert upload_storage.delete_local_upload(copied_url) is True
    assert source.read_bytes() == b"webp-content"


def test_copy_local_upload_keeps_external_url(monkeypatch, tmp_path):
    upload_storage = _reload_upload_storage(monkeypatch, tmp_path)

    assert (
        upload_storage.copy_local_upload(
            url="https://example.com/prize.webp",
            club_id=1,
            kind="case_item",
        )
        == "https://example.com/prize.webp"
    )
