from flask import flash, redirect, render_template, request, session, url_for

from app.core import owner_required
from app.services.dashboard import get_dashboard_audience_stats, get_visit_heatmap_stats
from app.services.pc_heatmap import get_pc_hours_heatmap_stats

from . import owner_bp


@owner_bp.route('/crm-analytics')
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

    telegram_only = request.args.get("telegram_only") in ("1", "true", "on", "yes")

    audience = get_dashboard_audience_stats(int(club_id), telegram_only=telegram_only)
    heatmap = get_visit_heatmap_stats(int(club_id), selected_period)
    pc_heatmap = get_pc_hours_heatmap_stats(int(club_id), selected_period)

    return render_template(
        "owner/crm_analytics.html",
        audience=audience,
        heatmap=heatmap,
        pc_heatmap=pc_heatmap,
        selected_period=selected_period,
        telegram_only=telegram_only,
    )
