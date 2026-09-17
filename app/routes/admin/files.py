from pathlib import Path

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from app.config import ADMIN_FILES_MAX_MB, ADMIN_FILES_REQUEST_MAX_MB
from app.core import admin_required
from app.routes.admin import admin_bp
from app.services.admin_drive import (
    AdminDriveError,
    create_folder,
    delete_file,
    delete_folder,
    get_drive_view,
    get_file,
    rename_file,
    rename_folder,
    save_file,
)


def _folder_redirect(folder_id: int | None):
    if folder_id is None:
        return redirect(url_for("admin.files"))
    return redirect(url_for("admin.files", folder=folder_id))


@admin_bp.get("/files")
@admin_required
def files():
    folder_id = request.args.get("folder", type=int)
    try:
        view = get_drive_view(folder_id, request.args.get("q"))
    except AdminDriveError:
        abort(404)
    return render_template(
        "admin/files.html",
        active_page="files",
        drive=view,
        max_file_mb=ADMIN_FILES_MAX_MB,
        request_max_mb=ADMIN_FILES_REQUEST_MAX_MB,
    )


@admin_bp.post("/files/folders")
@admin_required
def file_folder_create():
    parent_id = request.form.get("parent_id", type=int)
    try:
        create_folder(parent_id=parent_id, name=request.form.get("name"), created_by=session.get("user_id"))
        flash("Папка создана", "success")
    except AdminDriveError as exc:
        flash(str(exc), "error")
    return _folder_redirect(parent_id)


@admin_bp.post("/files/folders/<int:folder_id>/rename")
@admin_required
def file_folder_rename(folder_id: int):
    current_folder_id = request.form.get("current_folder_id", type=int)
    try:
        rename_folder(folder_id, request.form.get("name"))
        flash("Папка переименована", "success")
    except AdminDriveError as exc:
        flash(str(exc), "error")
    return _folder_redirect(current_folder_id)


@admin_bp.post("/files/folders/<int:folder_id>/delete")
@admin_required
def file_folder_delete(folder_id: int):
    current_folder_id = request.form.get("current_folder_id", type=int)
    try:
        delete_folder(folder_id)
        flash("Папка и всё её содержимое удалены", "success")
    except AdminDriveError as exc:
        flash(str(exc), "error")
    return _folder_redirect(current_folder_id)


@admin_bp.post("/files/upload")
@admin_required
def file_upload():
    request.max_content_length = int(ADMIN_FILES_REQUEST_MAX_MB or 250) * 1024 * 1024
    folder_id = request.form.get("folder_id", type=int)
    uploads = [item for item in request.files.getlist("files") if (item.filename or "").strip()]
    if not uploads:
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify(ok=False, error="Выберите хотя бы один файл"), 400
        flash("Выберите хотя бы один файл", "error")
        return _folder_redirect(folder_id)
    if len(uploads) > 20:
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify(ok=False, error="За один раз можно загрузить не больше 20 файлов"), 400
        flash("За один раз можно загрузить не больше 20 файлов", "error")
        return _folder_redirect(folder_id)

    uploaded = 0
    errors = []
    for item in uploads:
        try:
            save_file(folder_id=folder_id, file=item, uploaded_by=session.get("user_id"))
            uploaded += 1
        except AdminDriveError as exc:
            errors.append(f"{item.filename}: {exc}")

    if uploaded:
        flash(f"Загружено файлов: {uploaded}", "success")
    if errors:
        flash("Не удалось загрузить: " + "; ".join(errors[:4]), "error")
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(ok=not errors, uploaded=uploaded, errors=errors)
    return _folder_redirect(folder_id)


@admin_bp.post("/files/<int:file_id>/rename")
@admin_required
def file_rename(file_id: int):
    folder_id = request.form.get("folder_id", type=int)
    try:
        rename_file(file_id, request.form.get("name"))
        flash("Файл переименован", "success")
    except AdminDriveError as exc:
        flash(str(exc), "error")
    return _folder_redirect(folder_id)


@admin_bp.post("/files/<int:file_id>/delete")
@admin_required
def file_delete(file_id: int):
    folder_id = request.form.get("folder_id", type=int)
    try:
        delete_file(file_id)
        flash("Файл удалён", "success")
    except AdminDriveError as exc:
        flash(str(exc), "error")
    return _folder_redirect(folder_id)


@admin_bp.get("/files/<int:file_id>/download")
@admin_required
def file_download(file_id: int):
    try:
        item, path = get_file(file_id)
    except AdminDriveError:
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=item["original_name"],
        mimetype="application/octet-stream",
        conditional=True,
    )


@admin_bp.get("/files/<int:file_id>/preview")
@admin_required
def file_preview(file_id: int):
    try:
        item, path = get_file(file_id)
    except AdminDriveError:
        abort(404)
    if not item["previewable"]:
        abort(404)
    suffix = Path(item["original_name"]).suffix.lower()
    mimetype = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix)
    if not mimetype:
        abort(404)
    response = send_file(
        path,
        as_attachment=False,
        download_name=item["original_name"],
        mimetype=mimetype,
        conditional=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
