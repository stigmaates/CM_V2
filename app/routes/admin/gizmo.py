"""Admin-only stage setup, status and pause controls for Gizmo."""

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from app.core import admin_required, get_db_connection
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_onboarding import (
    pause_sync,
    public_connection,
    public_error,
    public_status,
    queue_setup,
)
from app.integrations.gizmo_sync import read_target
from app.integrations.stage import stage_pilot_available
from app.routes.admin import admin_bp


def target(club_id):
    if not stage_pilot_available():
        abort(404)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT club_id, name, integration_provider FROM clubs WHERE club_id=%s", (club_id,))
            club = cur.fetchone()
        if not club or club["integration_provider"] != "gizmo":
            abort(404)
        conn.rollback()
        return club
    finally:
        conn.close()


@admin_bp.route("/clubs/<int:club_id>/gizmo", methods=["GET", "POST"])
@admin_required
def gizmo_setup(club_id):
    club = target(club_id)
    conn = get_db_connection()
    try:
        if request.method == "POST":
            try:
                if request.form.get("action") == "pause":
                    pause_sync(conn, club_id)
                    flash("Обновления Gizmo приостановлены.", "success")
                else:
                    queue_setup(conn, club_id, request.form)
                    flash("Проверка и загрузка поставлены в очередь. Можно закрыть страницу.", "success")
            except (GizmoError, OSError, ValueError) as exc:
                flash(public_error(exc), "error")
            return redirect(url_for("admin.gizmo_setup", club_id=club_id))
        settings = read_target(conn, club_id, allow_initial=True)
        state = public_status(club_id)
        return render_template(
            "admin/gizmo_setup.html",
            club=club,
            connection=settings.get("source") or public_connection(club_id),
            state=state,
        )
    finally:
        conn.close()


@admin_bp.get("/clubs/<int:club_id>/gizmo/status")
@admin_required
def gizmo_status(club_id):
    target(club_id)
    try:
        response = jsonify(public_status(club_id))
    except (OSError, ValueError):
        response = jsonify(error="Не удалось прочитать состояние подключения.")
        response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response
