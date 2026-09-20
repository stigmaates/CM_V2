import os
import threading
from datetime import datetime

from flask import current_app, jsonify, render_template, request, session

from app.core import get_db_connection, owner_required
from app.services.mailing import (
    create_bonus_giveaway,
    create_mailing,
    delete_segment,
    get_crm_interaction_detail,
    get_crm_segment_options,
    get_filter_fields,
    get_message_variables,
    list_auto_mailings,
    list_bonus_giveaways,
    list_crm_interactions,
    list_mailings,
    list_segments,
    preview_recipients_count,
    save_segment,
    save_uploaded_file,
    update_auto_mailing_settings,
)
from app.services.outbound_policy import allow_manual_mailing_outbound, manual_mailings_only
from app.services.timezones import DEFAULT_CLUB_TIMEZONE, get_club_timezone_label
from scripts.process_mailings import process_one_mailing

from . import owner_bp


def get_current_club_id():
    return session.get("club_id")


def _process_mailing_in_background(mailing_id: int):
    conn = get_db_connection()
    try:
        with allow_manual_mailing_outbound():
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


@owner_bp.route("/mailing")
@owner_required
def mailing_page():
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
        crm_segments = get_crm_segment_options(conn, club_id)
        mailings = list_mailings(conn, club_id)
        auto_mailings = list_auto_mailings(conn, club_id)
        with conn.cursor() as cur:
            cur.execute("SELECT timezone FROM clubs WHERE club_id = %s LIMIT 1", (club_id,))
            club_row = cur.fetchone() or {}
        club_timezone_label = get_club_timezone_label(club_row.get("timezone") or DEFAULT_CLUB_TIMEZONE)
        bonus_giveaways = list_bonus_giveaways(conn, club_id)
        crm_interactions = list_crm_interactions(conn, club_id)
    finally:
        conn.close()

    return render_template(
        "owner/mailing.html",
        filter_fields=get_filter_fields(),
        message_variables=get_message_variables(),
        crm_segments=crm_segments,
        segments=segments,
        mailings=mailings,
        auto_mailings=auto_mailings,
        club_timezone_label=club_timezone_label,
        bonus_giveaways=bonus_giveaways,
        crm_interactions=crm_interactions,
    )


@owner_bp.route("/api/segments")
@owner_required
def api_segments():
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        segments = list_segments(conn, club_id)
    finally:
        conn.close()

    return jsonify({"ok": True, "segments": segments})


@owner_bp.route("/api/segments/preview", methods=["POST"])
@owner_required
def api_segments_preview():
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    rules = data.get("rules", [])

    conn = get_db_connection()
    try:
        count = preview_recipients_count(conn, club_id, rules, logic="and")
    finally:
        conn.close()

    return jsonify({"ok": True, "count": count})


@owner_bp.route("/api/segments/save", methods=["POST"])
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
        segment_id = save_segment(conn, club_id, name, rules, logic="and")
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "segment_id": segment_id})


@owner_bp.route("/api/segments/<int:segment_id>", methods=["DELETE"])
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


@owner_bp.route("/api/auto-mailings/<code>/toggle", methods=["POST"])
@owner_required
def api_auto_mailing_toggle(code):
    club_id = get_current_club_id()
    data = request.get_json(force=True)

    is_enabled = bool(data.get("is_enabled"))
    if is_enabled and manual_mailings_only():
        return jsonify({"ok": False, "error": "На тестовом стенде разрешены только ручные рассылки"}), 400

    days_inactive = None
    if "days_inactive" in data:
        try:
            days_inactive = int(data.get("days_inactive") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Количество дней неактива должно быть числом"}), 400
        if days_inactive < 1:
            return jsonify({"ok": False, "error": "Количество дней неактива должно быть больше 0"}), 400
        if days_inactive > 3650:
            return jsonify({"ok": False, "error": "Слишком большое количество дней неактива"}), 400

    bonus_amount = None
    if "bonus_amount" in data:
        try:
            bonus_amount = int(data.get("bonus_amount") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Количество бонусов должно быть числом"}), 400
        if bonus_amount < 1:
            return jsonify({"ok": False, "error": "Количество бонусов должно быть больше 0"}), 400
        if bonus_amount > 1000000:
            return jsonify({"ok": False, "error": "Слишком большое количество бонусов"}), 400

    delay_minutes = None
    if "delay_minutes" in data:
        try:
            delay_minutes = int(data.get("delay_minutes") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Задержка отправки должна быть числом"}), 400
        if delay_minutes < 1:
            return jsonify({"ok": False, "error": "Задержка отправки должна быть больше 0"}), 400
        if delay_minutes > 10080:
            return jsonify({"ok": False, "error": "Слишком большая задержка отправки"}), 400

    title = (data.get("title") or "").strip() if "title" in data else None
    if title is not None and not title:
        return jsonify({"ok": False, "error": "Укажи название авторассылки"}), 400

    description = (data.get("description") or "").strip() if "description" in data else None

    message_text = (data.get("message_text") or "").strip() if "message_text" in data else None
    if message_text is not None and not message_text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400

    send_start_time = None
    send_end_time = None
    if "send_start_time" in data or "send_end_time" in data:
        if "send_start_time" not in data or "send_end_time" not in data:
            return jsonify({"ok": False, "error": "Укажите начало и конец окна отправки"}), 400
        try:
            send_start_time = datetime.strptime(str(data.get("send_start_time") or ""), "%H:%M").strftime("%H:%M")
            send_end_time = datetime.strptime(str(data.get("send_end_time") or ""), "%H:%M").strftime("%H:%M")
        except ValueError:
            return jsonify({"ok": False, "error": "Время отправки указано неверно"}), 400
        if send_start_time == send_end_time:
            return jsonify({"ok": False, "error": "Начало и конец окна отправки должны отличаться"}), 400

    conn = get_db_connection()
    try:
        updated = update_auto_mailing_settings(
            conn,
            club_id,
            code,
            is_enabled=is_enabled,
            days_inactive=days_inactive,
            bonus_amount=bonus_amount,
            delay_minutes=delay_minutes,
            title=title,
            description=description,
            message_text=message_text,
            send_start_time=send_start_time,
            send_end_time=send_end_time,
        )
        conn.commit()
    finally:
        conn.close()

    if not updated:
        return jsonify({"ok": False, "error": "Авторассылка не найдена"}), 404

    return jsonify({"ok": True, "auto_mailing": updated})


@owner_bp.route("/api/mailings/upload", methods=["POST"])
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


@owner_bp.route("/api/mailings/create", methods=["POST"])
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
        with allow_manual_mailing_outbound():
            result = create_mailing(
                conn=conn,
                club_id=club_id,
                segment_id=segment_id,
                rules=rules,
                message_text=message_text,
                parse_mode=parse_mode,
                attachments=attachments,
                logic="and",
            )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        conn.rollback()
        current_app.logger.exception("Failed to create mailing for club %s", club_id)
        return jsonify({"ok": False, "error": "Не удалось создать рассылку"}), 500
    finally:
        conn.close()

    if start_now:
        _start_mailing_worker(result["mailing_id"])

    return jsonify({"ok": True, "started": start_now, **result})


@owner_bp.route("/api/bonus-giveaways/create", methods=["POST"])
@owner_required
def api_bonus_giveaways_create():
    club_id = get_current_club_id()
    data = request.get_json(force=True)
    rules = data.get("rules", [])
    bonus_amount_raw = data.get("bonus_amount")
    token_amount_raw = data.get("token_amount")
    message_text = (data.get("message_text") or "").strip()
    attachments = data.get("attachments", [])
    start_now = bool(data.get("start_now"))
    is_expiring = bool(data.get("is_expiring"))
    expires_value_raw = data.get("expires_value")
    expires_unit = (data.get("expires_unit") or "days").strip()

    try:
        bonus_amount = int(bonus_amount_raw or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Количество бонусов должно быть числом"}), 400

    try:
        token_amount = int(token_amount_raw or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Количество жетонов должно быть числом"}), 400

    if bonus_amount < 0:
        return jsonify({"ok": False, "error": "Количество бонусов не может быть отрицательным"}), 400

    if token_amount < 0:
        return jsonify({"ok": False, "error": "Количество жетонов не может быть отрицательным"}), 400

    if bonus_amount <= 0 and token_amount <= 0:
        return jsonify({"ok": False, "error": "Укажи бонусы или жетоны больше 0"}), 400

    expires_after_seconds = None
    if is_expiring:
        try:
            expires_value = int(expires_value_raw or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Срок сгорания должен быть числом"}), 400
        unit_seconds = {
            "minutes": 60,
            "hours": 60 * 60,
            "days": 24 * 60 * 60,
        }
        if expires_value < 1 or expires_unit not in unit_seconds:
            return jsonify({"ok": False, "error": "Укажи корректный срок сгорания раздачи"}), 400
        expires_after_seconds = expires_value * unit_seconds[expires_unit]

    if not message_text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400

    conn = get_db_connection()
    try:
        with allow_manual_mailing_outbound():
            result = create_bonus_giveaway(
                conn=conn,
                club_id=club_id,
                rules=rules,
                bonus_amount=bonus_amount,
                token_amount=token_amount,
                is_expiring=is_expiring,
                expires_after_seconds=expires_after_seconds,
                message_text=message_text,
                parse_mode="HTML",
                attachments=attachments,
                logic="and",
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


@owner_bp.route("/api/crm-interactions/<interaction_type>/<int:interaction_id>")
@owner_required
def api_crm_interaction_detail(interaction_type, interaction_id):
    club_id = get_current_club_id()
    conn = get_db_connection()
    try:
        detail = get_crm_interaction_detail(conn, club_id, interaction_type, interaction_id)
    finally:
        conn.close()

    if not detail:
        return jsonify({"ok": False, "error": "Взаимодействие не найдено"}), 404

    return jsonify({"ok": True, **detail})
