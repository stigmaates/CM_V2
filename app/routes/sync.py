from flask import flash, redirect, url_for

from app.core import login_required
from scripts.sync_guests_incremental import sync_guests_incremental
from scripts.sync_sessions_incremental import sync_sessions_incremental


def sync_guests_route():
    try:
        sync_guests_incremental()
        flash("Гости успешно синхронизированы", "success")
    except Exception as e:
        flash(f"Ошибка синхронизации гостей: {e}", "error")
    return redirect(url_for("settings"))


def sync_sessions_route():
    try:
        sync_sessions_incremental()
        flash("Сессии успешно синхронизированы", "success")
    except Exception as e:
        flash(f"Ошибка синхронизации сессий: {e}", "error")
    return redirect(url_for("settings"))


def register_sync_routes(app):
    app.add_url_rule('/sync/guests', view_func=login_required(sync_guests_route))
    app.add_url_rule('/sync/sessions', view_func=login_required(sync_sessions_route))
