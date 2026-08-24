import os
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from werkzeug.datastructures import FileStorage

from app.config import (
    CLUBMODULE_IMAGE_MAX_MB,
    CLUBMODULE_UPLOAD_QUOTA_MB,
    CLUBMODULE_UPLOAD_ROOT,
    CLUBMODULE_UPLOAD_URL_PREFIX,
)

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
UPLOAD_KIND_DIRS = {
    "case_cover": "covers",
    "case_item": "items",
}


class UploadError(ValueError):
    """User-facing error for invalid uploads."""


def _root_path() -> Path:
    return Path(CLUBMODULE_UPLOAD_ROOT).expanduser().resolve()


def _url_prefix() -> str:
    prefix = (CLUBMODULE_UPLOAD_URL_PREFIX or "/uploads").strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")


def get_quota_bytes() -> int:
    return int(CLUBMODULE_UPLOAD_QUOTA_MB or 25) * 1024 * 1024


def get_image_max_bytes() -> int:
    return int(CLUBMODULE_IMAGE_MAX_MB or 5) * 1024 * 1024


def _club_base_dir(club_id: int) -> Path:
    return _root_path() / "cases" / str(int(club_id))


def _kind_dir(club_id: int, kind: str) -> Path:
    folder = UPLOAD_KIND_DIRS.get(kind)
    if not folder:
        raise UploadError("Некорректный тип картинки")
    return _club_base_dir(club_id) / folder


def has_uploaded_file(file: FileStorage | None) -> bool:
    return bool(file and (file.filename or "").strip())


def get_club_upload_usage_bytes(club_id: int) -> int:
    base = _club_base_dir(club_id)
    if not base.exists():
        return 0

    total = 0
    for path in base.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def get_club_upload_usage_info(club_id: int) -> dict:
    used = get_club_upload_usage_bytes(club_id)
    limit = get_quota_bytes()
    remaining = max(0, limit - used)
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "remaining_bytes": remaining,
        "used_mb": round(used / 1024 / 1024, 2),
        "limit_mb": round(limit / 1024 / 1024, 2),
        "remaining_mb": round(remaining / 1024 / 1024, 2),
        "percent": round((used / limit) * 100, 1) if limit else 0,
    }


def is_local_upload_url(url: str | None) -> bool:
    if not url:
        return False
    value = str(url).strip()
    return value.startswith(_url_prefix() + "/cases/")


def _path_from_local_url(url: str | None) -> Path | None:
    if not is_local_upload_url(url):
        return None

    prefix = _url_prefix()
    rel = str(url).strip()[len(prefix) :].lstrip("/")
    root = _root_path()
    path = (root / rel).resolve()

    try:
        path.relative_to(root)
    except ValueError:
        return None

    return path


def get_local_upload_size(url: str | None) -> int:
    path = _path_from_local_url(url)
    if not path:
        return 0
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def delete_local_upload(url: str | None) -> bool:
    path = _path_from_local_url(url)
    if not path:
        return False

    try:
        if path.is_file():
            path.unlink()
            # Best-effort cleanup of empty parent folders up to club folder.
            root = _root_path()
            parent = path.parent
            while parent != root and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
            return True
    except OSError:
        return False

    return False


def copy_local_upload(*, url: str | None, club_id: int, kind: str) -> str | None:
    """Copy an uploaded image so duplicated entities do not share one file."""
    if not url or not is_local_upload_url(url):
        return url

    source_path = _path_from_local_url(url)
    if not source_path or not source_path.is_file():
        raise UploadError("Исходный файл картинки не найден. Загрузи картинку заново и повтори копирование.")

    save_dir = _kind_dir(club_id, kind)
    source_size = source_path.stat().st_size
    current_usage = get_club_upload_usage_bytes(club_id)
    quota = get_quota_bytes()
    if current_usage + source_size > quota:
        raise UploadError("Недостаточно места в хранилище клуба для копирования картинок кейса")

    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.webp"
    final_path = save_dir / filename
    tmp_path = save_dir / f".{filename}.tmp"

    try:
        tmp_path.write_bytes(source_path.read_bytes())
        os.replace(tmp_path, final_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

    public_rel = f"/cases/{int(club_id)}/{UPLOAD_KIND_DIRS[kind]}/{filename}"
    return _url_prefix() + public_rel


def validate_external_image_url(raw_url: str | None) -> str | None:
    value = (raw_url or "").strip()
    if not value:
        return None

    if value.startswith(_url_prefix() + "/"):
        return value

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value

    raise UploadError("Картинка должна быть http(s)-ссылкой или файлом, загруженным через форму")


def _check_extension(filename: str):
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise UploadError("Можно загрузить только JPG, PNG или WEBP. SVG/HTML и другие файлы запрещены.")


def _read_limited(file: FileStorage) -> bytes:
    max_bytes = get_image_max_bytes()
    data = file.stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadError(f"Файл слишком большой. Максимум — {CLUBMODULE_IMAGE_MAX_MB} МБ.")
    if not data:
        raise UploadError("Файл пустой")
    return data


def _convert_to_webp(data: bytes, kind: str) -> bytes:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise UploadError(
            "На сервере не установлена библиотека Pillow. Выполни: pip install -r requirements.txt"
        ) from exc

    try:
        Image.MAX_IMAGE_PIXELS = 20_000_000
        image = Image.open(BytesIO(data))
        image.verify()
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except Exception as exc:
        raise UploadError("Файл не похож на корректную картинку") from exc

    if not image.width or not image.height:
        raise UploadError("Не удалось определить размер картинки")

    max_size = (1200, 900) if kind == "case_cover" else (900, 900)
    image.thumbnail(max_size, Image.Resampling.LANCZOS)

    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="WEBP", quality=82, method=6)
    return output.getvalue()


def save_uploaded_case_image(
    *,
    club_id: int,
    kind: str,
    file: FileStorage | None,
    replacing_url: str | None = None,
) -> str | None:
    """Validate, convert and save an uploaded image. Returns public /uploads/... URL.

    replacing_url is used only for quota calculation. It is not deleted here;
    delete it after the DB update succeeds.
    """
    if not has_uploaded_file(file):
        return None

    _check_extension(file.filename or "")
    raw = _read_limited(file)
    webp_data = _convert_to_webp(raw, kind)

    save_dir = _kind_dir(club_id, kind)
    save_dir.mkdir(parents=True, exist_ok=True)

    current_usage = get_club_upload_usage_bytes(club_id)
    replaced_size = get_local_upload_size(replacing_url)
    projected_usage = current_usage - replaced_size + len(webp_data)
    quota = get_quota_bytes()

    if projected_usage > quota:
        used_mb = round(current_usage / 1024 / 1024, 2)
        limit_mb = round(quota / 1024 / 1024, 2)
        remaining_mb = round(max(0, quota - current_usage) / 1024 / 1024, 2)
        raise UploadError(
            f"Превышен лимит хранения картинок клуба: {used_mb} из {limit_mb} МБ. "
            f"Осталось примерно {remaining_mb} МБ. Удали старые картинки или загрузи файл меньше."
        )

    filename = f"{uuid.uuid4().hex}.webp"
    final_path = save_dir / filename
    tmp_path = save_dir / f".{filename}.tmp"

    try:
        tmp_path.write_bytes(webp_data)
        os.replace(tmp_path, final_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

    public_rel = f"/cases/{int(club_id)}/{UPLOAD_KIND_DIRS[kind]}/{filename}"
    return _url_prefix() + public_rel
