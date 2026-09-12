from flask import abort, jsonify, render_template, request, session

from app.core import get_db_connection, owner_required
from app.services.team import load_report, save_admin_settings

from . import owner_bp


@owner_bp.get("/team")
@owner_required
def team():
    if not session.get("club_id"):
        abort(403)
    return render_template("owner/team.html")


@owner_bp.get("/api/team")
@owner_required
def team_data():
    if not session.get("club_id"):
        abort(403)
    conn = get_db_connection()
    try:
        return jsonify(ok=True, **load_report(conn, int(session["club_id"]), request.args))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    finally:
        conn.close()


@owner_bp.post("/api/team/admins")
@owner_required
def team_admin_settings():
    if not session.get("club_id"):
        abort(403)
    body = request.get_json(silent=True) or {}
    conn = get_db_connection()
    try:
        save_admin_settings(conn, int(session["club_id"]), body.get("admins"))
        return jsonify(ok=True)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    finally:
        conn.close()
