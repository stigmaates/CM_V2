from flask import flash, redirect, render_template, request, session, url_for

from app.core import owner_required
from app.services.clubs import get_club_info
from app.services.dashboard import (
    get_case_openings_chart,
    get_dashboard_engagement_stats,
    get_dashboard_stats,
    get_first_visit_feedback_stats,
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
    first_visit_feedback = get_first_visit_feedback_stats(int(club_id), period)

    return render_template(
        "owner/dashboard.html",
        club=club,
        stats=stats,
        engagement=engagement,
        engagement_all_time_data=engagement_all_time_data,
        case_openings_chart=case_openings_chart,
        first_visit_feedback=first_visit_feedback,
        selected_period=period,
    )
