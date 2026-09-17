from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage

from app.config import ADMIN_FILES_MAX_MB, ADMIN_FILES_QUOTA_MB, ADMIN_FILES_ROOT, CLUBMODULE_UPLOAD_ROOT
from app.core import get_db_connection

MAX_NAME_LENGTH = 255
STORED_NAME_RE = re.compile(r"^[a-f0-9]{32}$")
PREVIEW_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
ARCHIVE_SUFFIXES = {".7z", ".gz", ".rar", ".tar", ".zip"}
SHEET_SUFFIXES = {".csv", ".ods", ".xls", ".xlsx"}
DOC_SUFFIXES = {".doc", ".docx", ".odt", ".pdf", ".ppt", ".pptx", ".txt"}


class AdminDriveError(ValueError):
    pass


def storage_root() -> Path:
    root = Path(ADMIN_FILES_ROOT).expanduser().resolve()
    public_root = Path(CLUBMODULE_UPLOAD_ROOT).expanduser().resolve()
    try:
        root.relative_to(public_root)
    except ValueError:
        return root
    raise AdminDriveError("ADMIN_FILES_ROOT должен находиться вне публичного CLUBMODULE_UPLOAD_ROOT")


def max_file_bytes() -> int:
    return int(ADMIN_FILES_MAX_MB or 100) * 1024 * 1024


def quota_bytes() -> int:
    return int(ADMIN_FILES_QUOTA_MB or 2048) * 1024 * 1024


def clean_item_name(value: str | None, *, kind: str) -> str:
    name = (value or "").replace("\x00", "").strip()
    if kind == "file":
        name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise AdminDriveError("Укажите название")
    if "/" in name or "\\" in name:
        raise AdminDriveError("В названии нельзя использовать / или \\")
    if len(name) > MAX_NAME_LENGTH:
        raise AdminDriveError(f"Название должно быть не длиннее {MAX_NAME_LENGTH} символов")
    return name


def format_bytes(value: int | None) -> str:
    size = max(0, int(value or 0))
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "Б":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f}".replace(".0", "") + f" {unit}"
        amount /= 1024
    return f"{size} Б"


def _file_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in PREVIEW_IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in SHEET_SUFFIXES:
        return "sheet"
    if suffix in DOC_SUFFIXES:
        return "document"
    if suffix in {".mp4", ".mov", ".mkv", ".webm"}:
        return "video"
    return "file"


def _decorate_file(row: dict) -> dict:
    item = dict(row)
    item["size_label"] = format_bytes(item.get("size_bytes"))
    item["kind"] = _file_kind(str(item.get("original_name") or ""))
    item["previewable"] = item["kind"] in {"image", "pdf"}
    return item


def _folder_exists(cursor, folder_id: int | None) -> bool:
    if folder_id is None:
        return True
    cursor.execute("SELECT id FROM admin_drive_folders WHERE id = %s LIMIT 1", (folder_id,))
    return bool(cursor.fetchone())


def get_drive_view(folder_id: int | None = None, query: str | None = None) -> dict:
    search = (query or "").strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not _folder_exists(cursor, folder_id):
                raise AdminDriveError("Папка не найдена")

            folder_sql = "parent_id IS NULL" if folder_id is None else "parent_id = %s"
            file_sql = "folder_id IS NULL" if folder_id is None else "folder_id = %s"
            folder_params: list[object] = [] if folder_id is None else [folder_id]
            file_params: list[object] = [] if folder_id is None else [folder_id]
            if search:
                folder_sql += " AND name LIKE %s"
                file_sql += " AND original_name LIKE %s"
                pattern = f"%{search}%"
                folder_params.append(pattern)
                file_params.append(pattern)

            cursor.execute(
                f"""
                SELECT id, parent_id, name, created_at, updated_at
                FROM admin_drive_folders
                WHERE {folder_sql}
                ORDER BY name, id
                """,
                folder_params,
            )
            folders = list(cursor.fetchall())
            cursor.execute(
                f"""
                SELECT id, folder_id, original_name, mime_type, size_bytes, created_at, updated_at
                FROM admin_drive_files
                WHERE {file_sql}
                ORDER BY original_name, id
                """,
                file_params,
            )
            files = [_decorate_file(row) for row in cursor.fetchall()]

            breadcrumbs = []
            current_id = folder_id
            visited = set()
            while current_id is not None and current_id not in visited:
                visited.add(current_id)
                cursor.execute(
                    "SELECT id, parent_id, name FROM admin_drive_folders WHERE id = %s LIMIT 1",
                    (current_id,),
                )
                row = cursor.fetchone()
                if not row:
                    break
                breadcrumbs.append(dict(row))
                current_id = row["parent_id"]
            breadcrumbs.reverse()

            cursor.execute("SELECT COALESCE(SUM(size_bytes), 0) AS used_bytes FROM admin_drive_files")
            used = int(cursor.fetchone()["used_bytes"] or 0)
    finally:
        conn.close()

    limit = quota_bytes()
    return {
        "folder_id": folder_id,
        "folders": folders,
        "files": files,
        "breadcrumbs": breadcrumbs,
        "query": search,
        "usage": {
            "used_bytes": used,
            "limit_bytes": limit,
            "used_label": format_bytes(used),
            "limit_label": format_bytes(limit),
            "remaining_label": format_bytes(max(0, limit - used)),
            "percent": round((used / limit) * 100, 1) if limit else 0,
        },
    }


def create_folder(*, parent_id: int | None, name: str | None, created_by: int | None) -> int:
    clean_name = clean_item_name(name, kind="folder")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not _folder_exists(cursor, parent_id):
                raise AdminDriveError("Родительская папка не найдена")
            parent_sql = "parent_id IS NULL" if parent_id is None else "parent_id = %s"
            params = (clean_name,) if parent_id is None else (parent_id, clean_name)
            cursor.execute(
                f"SELECT id FROM admin_drive_folders WHERE {parent_sql} AND name = %s LIMIT 1",
                params,
            )
            if cursor.fetchone():
                raise AdminDriveError("Папка с таким названием уже существует здесь")
            cursor.execute(
                "INSERT INTO admin_drive_folders (parent_id, name, created_by) VALUES (%s, %s, %s)",
                (parent_id, clean_name, created_by),
            )
            folder_pk = int(cursor.lastrowid)
        conn.commit()
        return folder_pk
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rename_folder(folder_id: int, name: str | None) -> None:
    clean_name = clean_item_name(name, kind="folder")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT parent_id FROM admin_drive_folders WHERE id = %s LIMIT 1", (folder_id,))
            folder = cursor.fetchone()
            if not folder:
                raise AdminDriveError("Папка не найдена")
            parent_id = folder["parent_id"]
            parent_sql = "parent_id IS NULL" if parent_id is None else "parent_id = %s"
            params = (folder_id, clean_name) if parent_id is None else (parent_id, folder_id, clean_name)
            cursor.execute(
                f"SELECT id FROM admin_drive_folders WHERE {parent_sql} AND id <> %s AND name = %s LIMIT 1",
                params,
            )
            if cursor.fetchone():
                raise AdminDriveError("Папка с таким названием уже существует здесь")
            cursor.execute("UPDATE admin_drive_folders SET name = %s WHERE id = %s", (clean_name, folder_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _read_upload(file: FileStorage) -> bytes:
    maximum = max_file_bytes()
    data = file.stream.read(maximum + 1)
    if not data:
        raise AdminDriveError("Файл пустой")
    if len(data) > maximum:
        raise AdminDriveError(f"Файл слишком большой. Максимум — {ADMIN_FILES_MAX_MB} МБ")
    return data


def save_file(*, folder_id: int | None, file: FileStorage | None, uploaded_by: int | None) -> int:
    if not file or not (file.filename or "").strip():
        raise AdminDriveError("Выберите файл")
    original_name = clean_item_name(file.filename, kind="file")
    data = _read_upload(file)
    stored_name = uuid.uuid4().hex
    root = storage_root()
    objects_dir = root / "objects"
    try:
        objects_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AdminDriveError("Хранилище файлов недоступно для записи") from exc
    final_path = objects_dir / stored_name
    tmp_path = objects_dir / f".{stored_name}.tmp"
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not _folder_exists(cursor, folder_id):
                raise AdminDriveError("Папка не найдена")
            cursor.execute("SELECT COALESCE(SUM(size_bytes), 0) AS used_bytes FROM admin_drive_files")
            used = int(cursor.fetchone()["used_bytes"] or 0)
            if used + len(data) > quota_bytes():
                raise AdminDriveError("Недостаточно места на диске. Удалите ненужные файлы или увеличьте лимит")
            tmp_path.write_bytes(data)
            os.replace(tmp_path, final_path)
            cursor.execute(
                """
                INSERT INTO admin_drive_files
                    (folder_id, stored_name, original_name, mime_type, size_bytes, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    folder_id,
                    stored_name,
                    original_name,
                    (file.mimetype or "application/octet-stream")[:160],
                    len(data),
                    uploaded_by,
                ),
            )
            file_pk = int(cursor.lastrowid)
        conn.commit()
        return file_pk
    except OSError as exc:
        conn.rollback()
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise AdminDriveError("Не удалось сохранить файл в хранилище") from exc
    except Exception:
        conn.rollback()
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        conn.close()


def rename_file(file_id: int, name: str | None) -> None:
    clean_name = clean_item_name(name, kind="file")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM admin_drive_files WHERE id = %s LIMIT 1", (file_id,))
            if not cursor.fetchone():
                raise AdminDriveError("Файл не найден")
            cursor.execute("UPDATE admin_drive_files SET original_name = %s WHERE id = %s", (clean_name, file_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _object_path(stored_name: str) -> Path:
    if not STORED_NAME_RE.fullmatch(stored_name or ""):
        raise AdminDriveError("Некорректный путь файла")
    root = storage_root()
    path = (root / "objects" / stored_name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AdminDriveError("Некорректный путь файла") from exc
    return path


def get_file(file_id: int) -> tuple[dict, Path]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, folder_id, stored_name, original_name, mime_type, size_bytes, created_at, updated_at
                FROM admin_drive_files WHERE id = %s LIMIT 1
                """,
                (file_id,),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise AdminDriveError("Файл не найден")
    path = _object_path(str(row["stored_name"]))
    if not path.is_file():
        raise AdminDriveError("Файл отсутствует в хранилище")
    return _decorate_file(row), path


def delete_file(file_id: int) -> None:
    conn = get_db_connection()
    stored_name = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT stored_name FROM admin_drive_files WHERE id = %s LIMIT 1", (file_id,))
            row = cursor.fetchone()
            if not row:
                raise AdminDriveError("Файл не найден")
            stored_name = str(row["stored_name"])
            cursor.execute("DELETE FROM admin_drive_files WHERE id = %s", (file_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        _object_path(stored_name).unlink(missing_ok=True)
    except OSError:
        pass


def delete_folder(folder_id: int) -> None:
    conn = get_db_connection()
    stored_names: list[str] = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, parent_id FROM admin_drive_folders")
            children: dict[int, list[int]] = {}
            existing = set()
            for row in cursor.fetchall():
                item_id = int(row["id"])
                existing.add(item_id)
                if row["parent_id"] is not None:
                    children.setdefault(int(row["parent_id"]), []).append(item_id)
            if folder_id not in existing:
                raise AdminDriveError("Папка не найдена")
            descendant_ids = []
            pending = [folder_id]
            while pending:
                item_id = pending.pop()
                descendant_ids.append(item_id)
                pending.extend(children.get(item_id, []))
            placeholders = ",".join(["%s"] * len(descendant_ids))
            cursor.execute(
                f"SELECT stored_name FROM admin_drive_files WHERE folder_id IN ({placeholders})",
                descendant_ids,
            )
            stored_names = [str(row["stored_name"]) for row in cursor.fetchall()]
            cursor.execute("DELETE FROM admin_drive_folders WHERE id = %s", (folder_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for stored_name in stored_names:
        try:
            _object_path(stored_name).unlink(missing_ok=True)
        except OSError:
            continue
