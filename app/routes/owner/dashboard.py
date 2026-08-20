from datetime import date, datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core import owner_required
from app.services.clubs import get_club_info
from app.services.dashboard import (
    get_case_openings_chart,
    get_case_openings_timeline,
    get_dashboard_engagement_stats,
    get_dashboard_stats,
    get_first_visit_feedback_stats,
    get_mission_completions_chart,
)

from . import owner_bp


@owner_bp.route("/dashboard")
@owner_required
def dashboard():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    period = request.args.get("period", "30").strip()
    try:
        period = int(period)
    except ValueError:
        period = 30
    if period not in (7, 30, 90):
        period = 30

    club = get_club_info(club_id)
    stats = get_dashboard_stats(int(club_id), period)
    engagement = get_dashboard_engagement_stats(int(club_id), period, all_time=False)
    engagement_all_time_data = get_dashboard_engagement_stats(int(club_id), period, all_time=True)
    case_openings_chart = get_case_openings_chart(int(club_id), period)
    mission_completions_chart = get_mission_completions_chart(int(club_id), period)
    first_visit_feedback = get_first_visit_feedback_stats(int(club_id), period)

    return render_template(
        "owner/dashboard.html",
        club=club,
        stats=stats,
        engagement=engagement,
        engagement_all_time_data=engagement_all_time_data,
        case_openings_chart=case_openings_chart,
        mission_completions_chart=mission_completions_chart,
        first_visit_feedback=first_visit_feedback,
        selected_period=period,
    )


@owner_bp.route("/api/dashboard/case-openings-timeline")
@owner_required
def case_openings_timeline():
    club_id = int(session.get("club_id") or 0)
    if not club_id:
        return jsonify({"ok": False, "error": "Клуб не выбран"}), 400

    period = request.args.get("period", "month").strip()
    group_by = request.args.get("group_by", "day").strip()
    today = date.today()

    if period == "week":
        date_from = today - timedelta(days=6)
        date_to = today
    elif period == "month":
        date_from = today - timedelta(days=29)
        date_to = today
    elif period == "custom":
        try:
            date_from = datetime.strptime(request.args.get("date_from", ""), "%Y-%m-%d").date()
            date_to = datetime.strptime(request.args.get("date_to", ""), "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"ok": False, "error": "Укажи корректный диапазон дат"}), 400
    else:
        return jsonify({"ok": False, "error": "Неизвестный период"}), 400

    if date_to < date_from:
        return jsonify({"ok": False, "error": "Дата окончания раньше даты начала"}), 400
    if (date_to - date_from).days > 365:
        return jsonify({"ok": False, "error": "Максимальный диапазон — 366 дней"}), 400
    if group_by not in {"day", "week", "month"}:
        return jsonify({"ok": False, "error": "Неизвестная группировка"}), 400

    timeline = get_case_openings_timeline(club_id, date_from, date_to, group_by)
    return jsonify(
        {
            "ok": True,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            **timeline,
        }
    )
