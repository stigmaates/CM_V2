from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core import get_db_connection, owner_required
from app.services.crm_analysis import get_crm_cohort_analysis
from app.services.dashboard import get_dashboard_audience_stats, get_visit_heatmap_stats
from app.services.mailing import (
    delete_segment,
    get_filter_fields,
    get_manual_crm_campaign_passport,
    list_manual_crm_campaigns,
    list_segments,
    save_segment,
)
from app.services.pc_heatmap import get_pc_hours_heatmap_stats

from . import owner_bp


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
    finally:
        conn.close()

    return render_template(
        "owner/crm_analytics.html",
        audience=audience,
        heatmap=heatmap,
        pc_heatmap=pc_heatmap,
        filter_fields=get_filter_fields(),
        cohorts=cohorts,
        initial_analysis=initial_analysis,
        manual_campaigns=manual_campaigns,
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
