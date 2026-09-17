from __future__ import annotations

import csv
import ipaddress
import socket
import tempfile
import zipfile
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.config import CLUBMODULE_UPLOAD_ROOT, CLUBMODULE_UPLOAD_URL_PREFIX
from app.core import get_db_connection

MAX_EXTERNAL_IMAGE_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 4
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"
CONTENT_TYPE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


class CaseImageExportError(ValueError):
    pass


def _safe_component(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split()).strip()
    for character in '<>:"/\\|?*':
        text = text.replace(character, "-")
    text = text.strip(" .")
    return (text or fallback)[:120]


def _safe_local_path(root: Path, relative: str) -> Path | None:
    try:
        path = (root / relative.lstrip("/")).resolve()
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def _local_image_path(raw_url: str) -> Path | None:
    parsed = urlparse(raw_url)
    url_path = parsed.path if parsed.scheme or parsed.netloc else raw_url.split("?", 1)[0]
    prefix = "/" + (CLUBMODULE_UPLOAD_URL_PREFIX or "/uploads").strip("/")
    if url_path.startswith(prefix + "/"):
        relative = url_path[len(prefix) :]
        return _safe_local_path(Path(CLUBMODULE_UPLOAD_ROOT).expanduser().resolve(), relative)
    if url_path.startswith("/static/"):
        return _safe_local_path(STATIC_ROOT.resolve(), url_path.removeprefix("/static/"))
    return None


def _validate_public_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise CaseImageExportError("Некорректная внешняя ссылка")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise CaseImageExportError("Не удалось определить адрес внешнего файла") from exc
    if not addresses:
        raise CaseImageExportError("Внешний адрес не найден")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise CaseImageExportError("Внешняя ссылка ведёт во внутреннюю сеть")
    return raw_url


def _download_external_image(client: httpx.Client, raw_url: str) -> tuple[bytes, str]:
    current_url = raw_url
    for _redirect in range(MAX_REDIRECTS + 1):
        _validate_public_url(current_url)
        with client.stream("GET", current_url, headers={"User-Agent": "CyberBonusCaseImageExport/1.0"}) as response:
            network_stream = response.extensions.get("network_stream")
            peer = network_stream.get_extra_info("server_addr") if network_stream else None
            if peer:
                peer_ip = ipaddress.ip_address(peer[0])
                if not peer_ip.is_global:
                    raise CaseImageExportError("Соединение с внешней ссылкой ушло во внутреннюю сеть")
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise CaseImageExportError("Внешний сервер вернул пустое перенаправление")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                raise CaseImageExportError("По ссылке получен не файл изображения")
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_EXTERNAL_IMAGE_BYTES:
                    raise CaseImageExportError("Внешнее изображение больше 25 МБ")
                chunks.append(chunk)
            if not size:
                raise CaseImageExportError("Внешний файл пустой")
            suffix = Path(urlparse(current_url).path).suffix.lower()
            if len(suffix) > 8 or not suffix.startswith("."):
                suffix = ""
            suffix = suffix or CONTENT_TYPE_EXTENSIONS.get(content_type, ".img")
            return b"".join(chunks), suffix
    raise CaseImageExportError("Слишком много перенаправлений")


def load_case_image_records() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 'case' AS image_type,
                       c.club_id, COALESCE(cl.name, CONCAT('Клуб ', c.club_id)) AS club_name,
                       c.id AS case_id, c.name AS case_name,
                       NULL AS item_id, NULL AS item_name, c.image_url
                FROM club_cases c
                LEFT JOIN clubs cl ON cl.club_id = c.club_id
                UNION ALL
                SELECT 'prize' AS image_type,
                       i.club_id, COALESCE(cl.name, CONCAT('Клуб ', i.club_id)) AS club_name,
                       i.case_id, COALESCE(c.name, CONCAT('Кейс ', i.case_id)) AS case_name,
                       i.id AS item_id, i.name AS item_name, i.image_url
                FROM club_case_items i
                LEFT JOIN club_cases c ON c.id = i.case_id AND c.club_id = i.club_id
                LEFT JOIN clubs cl ON cl.club_id = i.club_id
                ORDER BY club_id, case_id, image_type, item_id
                """)
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _archive_base_path(record: dict) -> str:
    club = f"{int(record['club_id'])}_{_safe_component(record.get('club_name'), 'Клуб')}"
    case = f"{int(record['case_id'])}_{_safe_component(record.get('case_name'), 'Кейс')}"
    return f"{club}/{case}"


def build_case_images_archive(records: list[dict]) -> tuple[Path, dict]:
    target = tempfile.NamedTemporaryFile(prefix="case_images_", suffix=".zip", delete=False)
    target_path = Path(target.name)
    target.close()
    manifest_rows = []
    added = 0
    missing = 0

    try:
        with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            with httpx.Client(timeout=httpx.Timeout(15, connect=8), follow_redirects=False, trust_env=False) as client:
                for record in records:
                    raw_url = str(record.get("image_url") or "").strip()
                    base_path = _archive_base_path(record)
                    item_name = ""
                    if record.get("image_type") == "case":
                        filename_base = "cover"
                    else:
                        item_name = _safe_component(record.get("item_name"), "Приз")
                        filename_base = f"prizes/{int(record['item_id'])}_{item_name}"

                    archive_path = ""
                    status = ""
                    error = ""
                    if not raw_url:
                        status = "no_image"
                        missing += 1
                    else:
                        try:
                            local_path = _local_image_path(raw_url)
                            if local_path:
                                suffix = local_path.suffix.lower() or ".img"
                                archive_path = f"{base_path}/{filename_base}{suffix}"
                                archive.write(local_path, archive_path)
                                status = "added_local"
                            else:
                                content, suffix = _download_external_image(client, raw_url)
                                archive_path = f"{base_path}/{filename_base}{suffix}"
                                archive.writestr(archive_path, content)
                                status = "added_external"
                            added += 1
                        except Exception as exc:
                            status = "failed"
                            error = str(exc)[:500]
                            missing += 1

                    manifest_rows.append(
                        {
                            "club_id": record.get("club_id"),
                            "club_name": record.get("club_name"),
                            "case_id": record.get("case_id"),
                            "case_name": record.get("case_name"),
                            "type": "Обложка кейса" if record.get("image_type") == "case" else "Изображение приза",
                            "item_id": record.get("item_id") or "",
                            "item_name": item_name,
                            "source_url": raw_url,
                            "archive_path": archive_path,
                            "status": status,
                            "error": error,
                        }
                    )

            manifest_buffer = StringIO()
            fields = [
                "club_id",
                "club_name",
                "case_id",
                "case_name",
                "type",
                "item_id",
                "item_name",
                "source_url",
                "archive_path",
                "status",
                "error",
            ]
            writer = csv.DictWriter(manifest_buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(manifest_rows)
            archive.writestr("manifest.csv", "\ufeff" + manifest_buffer.getvalue())
            archive.writestr(
                "README.txt",
                "Экспорт изображений кейсов Cyber Bonus\n"
                f"Записей в базе: {len(records)}\n"
                f"Добавлено изображений: {added}\n"
                f"Без изображения или с ошибкой: {missing}\n\n"
                "Подробности и исходные ссылки находятся в manifest.csv.\n",
            )
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    return target_path, {"records": len(records), "added": added, "missing": missing}


def export_case_images() -> tuple[Path, dict]:
    return build_case_images_archive(load_case_image_records())
