import os
import threading

from flask import current_app, jsonify, render_template, request, session

from app.core import get_db_connection, owner_required
from scripts.process_mailings import process_one_mailing
from app.services.mailing import (
    create_mailing,
    create_bonus_giveaway,
    delete_segment,
    get_filter_fields,
    get_crm_segment_options,
    list_auto_mailings,
    list_bonus_giveaways,
    list_mailings,
    list_segments,
    preview_recipients_count,
    save_segment,
    save_uploaded_file,
    update_auto_mailing_enabled,
)

from . import owner_bp


def get_current_club_id():
    return session.get("club_id")


def _process_mailing_in_background(mailing_id: int):
    conn = get_db_connection()
    try:
        process_one_mailing(conn, mailing_id)
    except Exception as exc:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mailings
                    SET status = 'failed',
                        failed_count = recipients_count,
                        finished_at = NOW()
                    WHERE id = %s
                    """,
                    (mailing_id,),
                )
                cur.execute(
                    """
                    UPDATE mailing_recipients
                    SET status = 'failed', error_text = %s
                    WHERE mailing_id = %s AND status = 'pending'
                    """,
                    (str(exc)[:1000], mailing_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
    finally:
        conn.close()


def _start_mailing_worker(mailing_id: int):
    thread = threading.Thread(
        target=_process_mailing_in_background,
        args=(mailing_id,),
        daemon=True,
    )
    thread.start()


@owner_bp.route('/mailing')
@owner_required
def mailing_page():
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
        crm_segments = get_crm_segment_options(conn, club_id)
        mailings = list_mailings(conn, club_id)
        auto_mailings = list_auto_mailings(conn, club_id)
        bonus_giveaways = list_bonus_giveaways(conn, club_id)
    finally:
        conn.close()

    return render_template(
        "owner/mailing.html",
        filter_fields=get_filter_fields(),
        crm_segments=crm_segments,
        segments=segments,
        mailings=mailings,
        auto_mailings=auto_mailings,
        bonus_giveaways=bonus_giveaways,
    )


@owner_bp.route('/api/segments')
@owner_required
def api_segments():
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
    finally:
        conn.close()

    return jsonify({"ok": True, "segments": segments})


@owner_bp.route('/api/segments/preview', methods=['POST'])
@owner_required
def api_segments_preview():
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    rules = data.get("rules", [])

    conn = get_db_connection()
    try:
        count = preview_recipients_count(conn, club_id, rules)
    finally:
        conn.close()

    return jsonify({"ok": True, "count": count})


@owner_bp.route('/api/segments/save', methods=['POST'])
@owner_required
def api_segments_save():
    club_id = get_current_club_id()
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


@owner_bp.route('/api/segments/<int:segment_id>', methods=['DELETE'])
@owner_required
def api_segments_delete(segment_id):
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        delete_segment(conn, club_id, segment_id)
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@owner_bp.route('/api/auto-mailings/<code>/toggle', methods=['POST'])
@owner_required
def api_auto_mailing_toggle(code):
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    is_enabled = bool(data.get("is_enabled"))

    conn = get_db_connection()
    try:
        updated = update_auto_mailing_enabled(conn, club_id, code, is_enabled)
        conn.commit()
    finally:
        conn.close()

    if not updated:
        return jsonify({"ok": False, "error": "Авторассылка не найдена"}), 404

    return jsonify({"ok": True, "code": code, "is_enabled": is_enabled})


@owner_bp.route('/api/mailings/upload', methods=['POST'])
@owner_required
def api_mailings_upload():
    club_id = get_current_club_id()

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


@owner_bp.route('/api/mailings/create', methods=['POST'])
@owner_required
def api_mailings_create():
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    rules = data.get("rules", [])
    segment_id = data.get("segment_id")
    message_text = (data.get("message_text") or "").strip()
    attachments = data.get("attachments", [])
    start_now = bool(data.get("start_now"))
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

    if start_now:
        _start_mailing_worker(result["mailing_id"])

    return jsonify({"ok": True, "started": start_now, **result})


@owner_bp.route('/api/bonus-giveaways/create', methods=['POST'])
@owner_required
def api_bonus_giveaways_create():
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    rules = data.get("rules", [])
    bonus_amount_raw = data.get("bonus_amount")
    message_text = (data.get("message_text") or "").strip()
    start_now = bool(data.get("start_now"))

    try:
        bonus_amount = int(bonus_amount_raw or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Количество бонусов должно быть числом"}), 400

    if bonus_amount <= 0:
        return jsonify({"ok": False, "error": "Количество бонусов должно быть больше 0"}), 400

    if not message_text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400

    conn = get_db_connection()
    try:
        result = create_bonus_giveaway(
            conn=conn,
            club_id=club_id,
            rules=rules,
            bonus_amount=bonus_amount,
            message_text=message_text,
            parse_mode="HTML",
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        conn.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()

    if start_now:
        _start_mailing_worker(result["mailing_id"])

    return jsonify({"ok": True, "started": start_now, **result})
