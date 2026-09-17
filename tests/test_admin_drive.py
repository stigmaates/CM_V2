import importlib
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

import app.services.admin_drive as admin_drive


@pytest.mark.parametrize(
    ("value", "kind", "expected"),
    [
        (" Референсы ", "folder", "Референсы"),
        ("C:\\fakepath\\prize image.png", "file", "prize image.png"),
        ("folder/subfolder/reference.pdf", "file", "reference.pdf"),
    ],
)
def test_admin_drive_cleans_item_names(value, kind, expected):
    assert admin_drive.clean_item_name(value, kind=kind) == expected


@pytest.mark.parametrize("value", ["", ".", "..", "folder/name", "folder\\name"])
def test_admin_drive_rejects_invalid_folder_names(value):
    with pytest.raises(admin_drive.AdminDriveError):
        admin_drive.clean_item_name(value, kind="folder")


def test_admin_drive_rejects_file_over_size_limit(monkeypatch):
    monkeypatch.setattr(admin_drive, "ADMIN_FILES_MAX_MB", 1)
    upload = FileStorage(stream=BytesIO(b"x" * (1024 * 1024 + 1)), filename="large.bin")

    with pytest.raises(admin_drive.AdminDriveError, match="слишком большой"):
        admin_drive._read_upload(upload)


def test_admin_drive_object_path_cannot_escape_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(admin_drive, "ADMIN_FILES_ROOT", str(tmp_path))
    monkeypatch.setattr(admin_drive, "CLUBMODULE_UPLOAD_ROOT", str(tmp_path / "public"))

    with pytest.raises(admin_drive.AdminDriveError):
        admin_drive._object_path("../secret")

    safe_path = admin_drive._object_path("a" * 32)
    assert safe_path == (tmp_path / "objects" / ("a" * 32)).resolve()


def test_admin_drive_refuses_public_upload_directory(monkeypatch, tmp_path):
    public_root = tmp_path / "public"
    monkeypatch.setattr(admin_drive, "CLUBMODULE_UPLOAD_ROOT", str(public_root))
    monkeypatch.setattr(admin_drive, "ADMIN_FILES_ROOT", str(public_root / "admin_drive"))

    with pytest.raises(admin_drive.AdminDriveError, match="вне публичного"):
        admin_drive.storage_root()


def test_admin_drive_formats_sizes_and_file_kinds():
    assert admin_drive.format_bytes(0) == "0 Б"
    assert admin_drive.format_bytes(1024) == "1 КБ"
    assert admin_drive._file_kind("reference.webp") == "image"
    assert admin_drive._file_kind("brief.pdf") == "pdf"
    assert admin_drive._file_kind("prizes.xlsx") == "sheet"


def test_admin_drive_migration_and_template_contract():
    migration = importlib.import_module("migrations.versions.0043_admin_drive")
    assert migration.revision == "0043_admin_drive"
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("admin_drive_folders" in value for value in constants)
    assert any("admin_drive_files" in value for value in constants)

    project_root = Path(__file__).resolve().parents[1]
    template = (project_root / "app/templates/admin/files.html").read_text()
    assert "data-drive-dropzone" in template
    assert "data-drive-new-folder" in template
    assert "data-drive-rename" in template
