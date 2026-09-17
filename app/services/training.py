from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from app.core import get_db_connection

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_TITLE_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 5000


class TrainingVideoError(ValueError):
    pass


def extract_youtube_video_id(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        raise TrainingVideoError("Вставьте ссылку на видео YouTube")
    if YOUTUBE_ID_RE.fullmatch(raw):
        return raw

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().rstrip(".")
    video_id = ""

    if host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path.rstrip("/") == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
            video_id = parts[1]
    else:
        raise TrainingVideoError("Нужна ссылка именно на YouTube")

    if not YOUTUBE_ID_RE.fullmatch(video_id):
        raise TrainingVideoError("Не удалось определить ролик по этой ссылке YouTube")
    return video_id


def _clean_fields(title: str | None, description: str | None) -> tuple[str, str]:
    clean_title = (title or "").strip()
    clean_description = (description or "").strip()
    if not clean_title:
        raise TrainingVideoError("Укажите название карточки")
    if not clean_description:
        raise TrainingVideoError("Добавьте описание видео")
    if len(clean_title) > MAX_TITLE_LENGTH:
        raise TrainingVideoError(f"Название должно быть не длиннее {MAX_TITLE_LENGTH} символов")
    if len(clean_description) > MAX_DESCRIPTION_LENGTH:
        raise TrainingVideoError(f"Описание должно быть не длиннее {MAX_DESCRIPTION_LENGTH} символов")
    return clean_title, clean_description


def video_urls(video_id: str) -> dict[str, str]:
    return {
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "embed_url": f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&autoplay=1",
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }


def serialize_training_video(row: dict) -> dict:
    item = dict(row)
    item.update(video_urls(str(item["youtube_video_id"])))
    item["is_active"] = bool(item.get("is_active"))
    return item


def list_training_videos(*, include_inactive: bool = False) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            where = "" if include_inactive else "WHERE is_active = 1"
            cursor.execute(f"""
                SELECT id, youtube_video_id, youtube_url, title, description,
                       sort_order, is_active, created_at, updated_at
                FROM training_videos
                {where}
                ORDER BY sort_order, id
                """)
            return [serialize_training_video(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def create_training_video(
    *, title: str | None, description: str | None, youtube_url: str | None, is_active: bool = True
) -> int:
    clean_title, clean_description = _clean_fields(title, description)
    video_id = extract_youtube_video_id(youtube_url)
    canonical_url = video_urls(video_id)["youtube_url"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM training_videos WHERE youtube_video_id = %s LIMIT 1",
                (video_id,),
            )
            if cursor.fetchone():
                raise TrainingVideoError("Этот ролик уже добавлен в обучение")
            cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM training_videos")
            next_order = int(cursor.fetchone()["next_order"])
            cursor.execute(
                """
                INSERT INTO training_videos
                    (youtube_video_id, youtube_url, title, description, sort_order, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (video_id, canonical_url, clean_title, clean_description, next_order, int(is_active)),
            )
            video_pk = int(cursor.lastrowid)
        conn.commit()
        return video_pk
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_training_video(
    video_pk: int,
    *,
    title: str | None,
    description: str | None,
    youtube_url: str | None,
    is_active: bool,
) -> None:
    clean_title, clean_description = _clean_fields(title, description)
    video_id = extract_youtube_video_id(youtube_url)
    canonical_url = video_urls(video_id)["youtube_url"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM training_videos WHERE id = %s LIMIT 1", (video_pk,))
            if not cursor.fetchone():
                raise TrainingVideoError("Карточка не найдена")
            cursor.execute(
                "SELECT id FROM training_videos WHERE youtube_video_id = %s AND id <> %s LIMIT 1",
                (video_id, video_pk),
            )
            if cursor.fetchone():
                raise TrainingVideoError("Этот ролик уже добавлен в обучение")
            cursor.execute(
                """
                UPDATE training_videos
                SET youtube_video_id = %s, youtube_url = %s, title = %s,
                    description = %s, is_active = %s
                WHERE id = %s
                """,
                (video_id, canonical_url, clean_title, clean_description, int(is_active), video_pk),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_training_video(video_pk: int) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM training_videos WHERE id = %s", (video_pk,))
            if cursor.rowcount != 1:
                raise TrainingVideoError("Карточка не найдена")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reorder_training_videos(video_ids: list[int]) -> None:
    if not video_ids or len(video_ids) != len(set(video_ids)):
        raise TrainingVideoError("Некорректный порядок карточек")
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM training_videos ORDER BY id")
            existing = {int(row["id"]) for row in cursor.fetchall()}
            if existing != set(video_ids):
                raise TrainingVideoError("Список карточек изменился. Обновите страницу и повторите сортировку")
            for sort_order, video_pk in enumerate(video_ids):
                cursor.execute(
                    "UPDATE training_videos SET sort_order = %s WHERE id = %s",
                    (sort_order, video_pk),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
