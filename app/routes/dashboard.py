from flask import flash, redirect, render_template, request, session, url_for

from app.core import login_required
from app.services.clubs import get_club_info
from app.services.dashboard import get_dashboard_engagement_stats, get_dashboard_stats


def dashboard():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    period = request.args.get("period", "30").strip()
    try:
        period = int(period)
    except ValueError:
        period = 30
    if period not in (7, 30, 90):
        period = 30

    club = get_club_info(club_id)
    stats = get_dashboard_stats(int(club_id), period)
    engagement = get_dashboard_engagement_stats(int(club_id), period)

    return render_template(
        "dashboard.html",
        club=club,
        stats=stats,
        engagement=engagement,
        selected_period=period,
    )


def register_dashboard_routes(app):
    app.add_url_rule("/dashboard", view_func=login_required(dashboard))
