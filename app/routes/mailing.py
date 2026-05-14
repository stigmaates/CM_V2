import os
from flask import current_app, jsonify, render_template, request, session

from app.core import get_db_connection
from app.services.mailing import (
    create_mailing,
    delete_segment,
    get_filter_fields,
    list_mailings,
    list_segments,
    preview_recipients_count,
    save_segment,
    save_uploaded_file,
)


def get_current_club_id():
    return session.get("club_id")


def mailing_page():
    club_id = get_current_club_id()
    if not club_id:
        return render_template("login.html"), 401

    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
        mailings = list_mailings(conn, club_id)
    finally:
        conn.close()

    return render_template(
        "mailing.html",
        filter_fields=get_filter_fields(),
        segments=segments,
        mailings=mailings,
    )


def api_segments():
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
    finally:
        conn.close()

    return jsonify({"ok": True, "segments": segments})


def api_segments_preview():
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    rules = data.get("rules", [])

    conn = get_db_connection()
    try:
        count = preview_recipients_count(conn, club_id, rules)
    finally:
        conn.close()

    return jsonify({"ok": True, "count": count})


def api_segments_save():
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    rules = data.get("rules", [])

    if not name:
        return jsonify({"ok": False, "error": "Укажи название сегмента"}), 400

    conn = get_db_connection()
    try:
        segment_id = save_segment(conn, club_id, name, rules)
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "segment_id": segment_id})


def api_segments_delete(segment_id):
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    conn = get_db_connection()
    try:
        delete_segment(conn, club_id, segment_id)
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


def api_mailings_upload():
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    if "files" not in request.files:
        return jsonify({"ok": False, "error": "Файлы не переданы"}), 400

    files = request.files.getlist("files")
    upload_dir = os.path.join(current_app.root_path, "..", "uploads", "mailings", str(club_id))

    uploaded = []
    for file_storage in files:
        if not file_storage or not file_storage.filename:
            continue
        item = save_uploaded_file(file_storage, upload_dir)
        uploaded.append(item)

    return jsonify({"ok": True, "files": uploaded})


def api_mailings_create():
    club_id = get_current_club_id()
    if not club_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    rules = data.get("rules", [])
    segment_id = data.get("segment_id")
    message_text = (data.get("message_text") or "").strip()
    attachments = data.get("attachments", [])
    parse_mode = "HTML"

    if not message_text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400

    conn = get_db_connection()
    try:
        result = create_mailing(
            conn=conn,
            club_id=club_id,
            segment_id=segment_id,
            rules=rules,
            message_text=message_text,
            parse_mode=parse_mode,
            attachments=attachments,
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, **result})


def register_mailing(app):
    app.add_url_rule("/mailing", view_func=mailing_page)
    app.add_url_rule("/api/segments", view_func=api_segments)
    app.add_url_rule("/api/segments/preview", view_func=api_segments_preview, methods=["POST"])
    app.add_url_rule("/api/segments/save", view_func=api_segments_save, methods=["POST"])
    app.add_url_rule("/api/segments/<int:segment_id>", view_func=api_segments_delete, methods=["DELETE"])
    app.add_url_rule("/api/mailings/upload", view_func=api_mailings_upload, methods=["POST"])
    app.add_url_rule("/api/mailings/create", view_func=api_mailings_create, methods=["POST"])