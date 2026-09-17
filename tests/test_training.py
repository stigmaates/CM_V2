import importlib
from pathlib import Path

import pytest

from app.services.training import TrainingVideoError, extract_youtube_video_id, serialize_training_video


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=18", "dQw4w9WgXcQ"),
        ("youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/live/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_youtube_video_id(value, expected):
    assert extract_youtube_video_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=too-short",
        "https://youtube.com/channel/dQw4w9WgXcQ",
    ],
)
def test_extract_youtube_video_id_rejects_invalid_values(value):
    with pytest.raises(TrainingVideoError):
        extract_youtube_video_id(value)


def test_serialize_training_video_adds_safe_player_and_preview_urls():
    item = serialize_training_video({"id": 7, "youtube_video_id": "dQw4w9WgXcQ", "is_active": 1})

    assert item["youtube_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert item["embed_url"].startswith("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
    assert item["thumbnail_url"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert item["is_active"] is True


def test_training_migration_exports_table_creation():
    migration = importlib.import_module("migrations.versions.0042_training_videos")

    assert migration.revision == "0042_training_videos"
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("CREATE TABLE IF NOT EXISTS training_videos" in value for value in constants)


def test_training_templates_include_player_and_admin_sorting():
    project_root = Path(__file__).resolve().parents[1]
    owner_template = (project_root / "app/templates/owner/training.html").read_text()
    admin_template = (project_root / "app/templates/admin/training.html").read_text()

    assert "data-training-player" in owner_template
    assert "thumbnail_url" in owner_template
    assert "data-training-sortable" in admin_template
    assert "data-youtube-url-input" in admin_template
