import threading

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core import get_db_connection, owner_required
from app.services.crm_analysis import get_crm_cohort_analysis
from app.services.crm_pulse import get_crm_pulse_groups
from app.services.dashboard import get_dashboard_audience_stats, get_visit_heatmap_stats
from app.services.mailing import (
    create_bonus_giveaway,
    create_mailing_for_recipients,
    delete_segment,
    get_filter_fields,
    get_manual_crm_campaign_passport,
    get_message_variables,
    get_recipient_rows_for_guest_ids,
    list_manual_crm_campaigns,
    list_segments,
    save_segment,
)
from app.services.pc_heatmap import get_pc_hours_heatmap_stats
from scripts.process_mailings import process_one_mailing

from . import owner_bp


def _process_crm_mailing_in_background(mailing_id: int):
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


def _start_crm_mailing_worker(mailing_id: int):
    thread = threading.Thread(
        target=_process_crm_mailing_in_background,
        args=(mailing_id,),
        daemon=True,
    )
    thread.start()


@owner_bp.route("/crm-analytics")
@owner_required
def crm_analytics():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    try:
        selected_period = int(request.args.get("period", 30))
    except (TypeError, ValueError):
        selected_period = 30

    if selected_period not in (7, 30, 90):
        selected_period = 30

    telegram_only = False

    audience = get_dashboard_audience_stats(int(club_id), telegram_only=telegram_only)
    heatmap = get_visit_heatmap_stats(int(club_id), selected_period)
    pc_heatmap = get_pc_hours_heatmap_stats(int(club_id), selected_period)
    conn = get_db_connection()
    try:
        cohorts = list_segments(conn, int(club_id))
        initial_analysis = get_crm_cohort_analysis(conn, int(club_id), [], funnel_period="all")
        manual_campaigns = list_manual_crm_campaigns(conn, int(club_id))
        crm_pulse_groups = get_crm_pulse_groups(conn, int(club_id))
    finally:
        conn.close()

    return render_template(
        "owner/crm_analytics.html",
        audience=audience,
        heatmap=heatmap,
        pc_heatmap=pc_heatmap,
        filter_fields=get_filter_fields(),
        message_variables=get_message_variables(),
        cohorts=cohorts,
        initial_analysis=initial_analysis,
        manual_campaigns=manual_campaigns,
        crm_pulse_groups=crm_pulse_groups,
        selected_period=selected_period,
        telegram_only=telegram_only,
    )


@owner_bp.route("/api/crm-analysis/preview", methods=["POST"])
@owner_required
def api_crm_analysis_preview():
    club_id = session.get("club_id")
    data = request.get_json(force=True)
    rules = data.get("rules", [])
    funnel_period = data.get("funnel_period", "all")
    funnel_date_from = data.get("funnel_date_from")
    funnel_date_to = data.get("funnel_date_to")

    conn = get_db_connection()
    try:
        analysis = get_crm_cohort_analysis(
            conn,
            int(club_id),
            rules,
            funnel_period=funnel_period,
            funnel_date_from=funnel_date_from,
            funnel_date_to=funnel_date_to,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()

    return jsonify({"ok": True, "analysis": analysis})


@owner_bp.route("/api/crm-cohorts/save", methods=["POST"])
@owner_required
def api_crm_cohort_save():
    club_id = session.get("club_id")
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    rules = data.get("rules", [])
    if not name:
        return jsonify({"ok": False, "error": "Укажи название когорты"}), 400

    conn = get_db_connection()
    try:
        cohort_id = save_segment(conn, int(club_id), name, rules)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()

    return jsonify({"ok": True, "cohort_id": cohort_id})


@owner_bp.route("/api/crm-cohorts/<int:cohort_id>", methods=["DELETE"])
@owner_required
def api_crm_cohort_delete(cohort_id):
    club_id = session.get("club_id")
    conn = get_db_connection()
    try:
        delete_segment(conn, int(club_id), cohort_id)
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@owner_bp.route("/api/crm-campaigns/<campaign_type>/<int:campaign_id>")
@owner_required
def api_crm_campaign_passport(campaign_type, campaign_id):
    club_id = session.get("club_id")
    conn = get_db_connection()
    try:
        passport = get_manual_crm_campaign_passport(conn, int(club_id), campaign_type, campaign_id)
    finally:
        conn.close()

    if not passport:
        return jsonify({"ok": False, "error": "Кампания не найдена"}), 404
    return jsonify({"ok": True, "passport": passport})


@owner_bp.route("/api/crm-pulse/interact", methods=["POST"])
@owner_required
def api_crm_pulse_interact():
    club_id = session.get("club_id")
    data = request.get_json(force=True)
    guest_ids = data.get("guest_ids") or []
    message_text = (data.get("message_text") or "").strip()
    transition = data.get("transition") or {}

    try:
        bonus_amount = int(data.get("bonus_amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Количество бонусов должно быть числом"}), 400

    try:
        token_amount = int(data.get("token_amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Количество жетонов должно быть числом"}), 400

    if bonus_amount < 0:
        return jsonify({"ok": False, "error": "Количество бонусов не может быть отрицательным"}), 400
    if token_amount < 0:
        return jsonify({"ok": False, "error": "Количество жетонов не может быть отрицательным"}), 400
    if not message_text:
        return jsonify({"ok": False, "error": "Сообщение пустое"}), 400

    is_expiring = bool(data.get("is_expiring"))
    expires_after_seconds = None
    if is_expiring:
        if bonus_amount <= 0:
            return jsonify({"ok": False, "error": "Сгорающий бонус можно включить только для КБ"}), 400
        try:
            expires_value = int(data.get("expires_value") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Срок сгорания должен быть числом"}), 400
        unit_seconds = {"minutes": 60, "hours": 60 * 60, "days": 24 * 60 * 60}
        expires_unit = (data.get("expires_unit") or "days").strip()
        if expires_value < 1 or expires_unit not in unit_seconds:
            return jsonify({"ok": False, "error": "Укажи корректный срок сгорания"}), 400
        expires_after_seconds = expires_value * unit_seconds[expires_unit]

    conn = get_db_connection()
    try:
        recipients = get_recipient_rows_for_guest_ids(conn, int(club_id), guest_ids)
        if not recipients:
            return jsonify({"ok": False, "error": "У выбранных гостей нет привязанного Telegram"}), 400

        filters_json = {
            "type": "crm_pulse",
            "guest_ids": [int(row["guest_id"]) for row in recipients],
            "requested_guest_ids": [int(guest_id) for guest_id in guest_ids if str(guest_id).strip().isdigit()],
            "transition": transition,
        }

        if bonus_amount > 0 or token_amount > 0:
            result = create_bonus_giveaway(
                conn=conn,
                club_id=int(club_id),
                rules=[],
                bonus_amount=bonus_amount,
                token_amount=token_amount,
                is_expiring=is_expiring,
                expires_after_seconds=expires_after_seconds,
                message_text=message_text,
                parse_mode="HTML",
                recipient_rows=recipients,
                filters_json_extra=filters_json,
            )
        else:
            result = create_mailing_for_recipients(
                conn=conn,
                club_id=int(club_id),
                recipients=recipients,
                message_text=message_text,
                parse_mode="HTML",
                filters_json=filters_json,
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

    _start_crm_mailing_worker(int(result["mailing_id"]))
    return jsonify({"ok": True, "started": True, **result})
