import csv
import socket
import zipfile
from io import StringIO

import pytest

import app.services.case_image_export as case_image_export


def test_safe_component_removes_archive_separators():
    assert case_image_export._safe_component('  Кейс: "Топ/дроп"  ', "Кейс") == "Кейс- -Топ-дроп-"
    assert case_image_export._safe_component("", "Кейс") == "Кейс"


def test_public_url_validation_rejects_private_address(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )

    with pytest.raises(case_image_export.CaseImageExportError, match="внутреннюю сеть"):
        case_image_export._validate_public_url("http://images.example.test/prize.png")


def test_build_case_images_archive_includes_local_files_and_manifest(monkeypatch, tmp_path):
    upload_root = tmp_path / "uploads"
    cover = upload_root / "cases" / "4" / "covers" / "cover.webp"
    prize = upload_root / "cases" / "4" / "items" / "prize.png"
    cover.parent.mkdir(parents=True)
    prize.parent.mkdir(parents=True)
    cover.write_bytes(b"cover-image")
    prize.write_bytes(b"prize-image")
    monkeypatch.setattr(case_image_export, "CLUBMODULE_UPLOAD_ROOT", str(upload_root))
    monkeypatch.setattr(case_image_export, "CLUBMODULE_UPLOAD_URL_PREFIX", "/uploads")

    records = [
        {
            "image_type": "case",
            "club_id": 4,
            "club_name": "Новый / клуб",
            "case_id": 10,
            "case_name": "Кейс: №1",
            "item_id": None,
            "item_name": None,
            "image_url": "/uploads/cases/4/covers/cover.webp",
        },
        {
            "image_type": "prize",
            "club_id": 4,
            "club_name": "Новый / клуб",
            "case_id": 10,
            "case_name": "Кейс: №1",
            "item_id": 25,
            "item_name": "100 / бонусов",
            "image_url": "/uploads/cases/4/items/prize.png",
        },
        {
            "image_type": "prize",
            "club_id": 4,
            "club_name": "Новый / клуб",
            "case_id": 10,
            "case_name": "Кейс: №1",
            "item_id": 26,
            "item_name": "Без картинки",
            "image_url": None,
        },
    ]

    archive_path, summary = case_image_export.build_case_images_archive(records)
    try:
        assert summary == {"records": 3, "added": 2, "missing": 1}
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            assert "4_Новый - клуб/10_Кейс- №1/cover.webp" in names
            assert "4_Новый - клуб/10_Кейс- №1/prizes/25_100 - бонусов.png" in names
            assert archive.read("4_Новый - клуб/10_Кейс- №1/cover.webp") == b"cover-image"
            rows = list(csv.DictReader(StringIO(archive.read("manifest.csv").decode("utf-8-sig"))))
            assert [row["status"] for row in rows] == ["added_local", "added_local", "no_image"]
            assert "Добавлено изображений: 2" in archive.read("README.txt").decode("utf-8")
    finally:
        archive_path.unlink(missing_ok=True)
