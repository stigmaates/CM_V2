from flask import flash, jsonify, redirect, render_template, request, url_for

from app.core import admin_required
from app.routes.admin import admin_bp
from app.services.training import (
    TrainingVideoError,
    create_training_video,
    delete_training_video,
    list_training_videos,
    reorder_training_videos,
    update_training_video,
)


@admin_bp.get("/training")
@admin_required
def training():
    return render_template(
        "admin/training.html",
        active_page="training",
        videos=list_training_videos(include_inactive=True),
    )


@admin_bp.post("/training/videos")
@admin_required
def training_video_create():
    try:
        create_training_video(
            title=request.form.get("title"),
            description=request.form.get("description"),
            youtube_url=request.form.get("youtube_url"),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Видео добавлено в обучение", "success")
    except TrainingVideoError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.training"))


@admin_bp.post("/training/videos/<int:video_pk>/update")
@admin_required
def training_video_update(video_pk: int):
    try:
        update_training_video(
            video_pk,
            title=request.form.get("title"),
            description=request.form.get("description"),
            youtube_url=request.form.get("youtube_url"),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Карточка обновлена", "success")
    except TrainingVideoError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.training"))


@admin_bp.post("/training/videos/<int:video_pk>/delete")
@admin_required
def training_video_delete(video_pk: int):
    try:
        delete_training_video(video_pk)
        flash("Карточка удалена", "success")
    except TrainingVideoError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.training"))


@admin_bp.post("/training/reorder")
@admin_required
def training_video_reorder():
    payload = request.get_json(silent=True) or {}
    try:
        raw_ids = payload.get("ids")
        if not isinstance(raw_ids, list):
            raise TrainingVideoError("Некорректный порядок карточек")
        reorder_training_videos([int(item) for item in raw_ids])
        return jsonify(ok=True)
    except (TypeError, ValueError, TrainingVideoError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
