from flask import jsonify, redirect, session, url_for

from app.config import APP_VERSION, GIT_COMMIT
from app.core import get_db_connection

from . import public_bp


@public_bp.route("/healthz")
def healthz():
    return jsonify(
        {
            "ok": True,
            "service": "cyber-bonus",
            "version": APP_VERSION,
            "commit": GIT_COMMIT or None,
        }
    )


@public_bp.route("/readyz")
def readyz():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            row = cursor.fetchone() or {}
        if int(row.get("ok") or 0) != 1:
            raise RuntimeError("unexpected database response")
    except Exception:
        return (
            jsonify(
                {
                    "ok": False,
                    "service": "cyber-bonus",
                    "version": APP_VERSION,
                    "commit": GIT_COMMIT or None,
                    "database": "unavailable",
                }
            ),
            503,
        )
    finally:
        if conn:
            conn.close()

    return jsonify(
        {
            "ok": True,
            "service": "cyber-bonus",
            "version": APP_VERSION,
            "commit": GIT_COMMIT or None,
            "database": "available",
        }
    )


@public_bp.route("/")
def index():
    if session.get("guest_logged_in"):
        return redirect(url_for("guest.dashboard"))
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin.users_create"))
        if session.get("role") == "reception":
            return redirect(url_for("reception.dashboard"))
        return redirect(url_for("owner.dashboard"))
    return redirect(url_for("auth.login"))


@public_bp.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """Fallback static serving for uploaded images.

    In production Nginx may serve /uploads/ directly. If it is not configured yet,
    Flask will still return uploaded case/prize images from CLUBMODULE_UPLOAD_ROOT.
    """
    from pathlib import Path

    from flask import abort, send_from_directory

    from app.config import CLUBMODULE_UPLOAD_ROOT

    parts = filename.split("/")
    if (
        not filename
        or filename.startswith("/")
        or ".." in parts
        or any(part.startswith(".") for part in parts)
        or Path(filename).suffix.lower() not in {".webp", ".png", ".jpg", ".jpeg"}
    ):
        abort(404)

    return send_from_directory(CLUBMODULE_UPLOAD_ROOT, filename, max_age=86400)
