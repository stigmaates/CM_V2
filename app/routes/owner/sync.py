from flask import flash, redirect, session, url_for

from app.core import owner_required
from scripts.sync_guests_incremental import sync_guests_incremental
from scripts.sync_sessions_incremental import sync_sessions_incremental

from . import owner_bp


def _current_club_id():
    club_id = session.get("club_id")
    if not club_id:
        raise Exception("Клуб не найден в сессии")
    return int(club_id)


@owner_bp.route("/sync/guests")
@owner_required
def sync_guests_route():
    try:
        sync_guests_incremental(_current_club_id())
        flash("Гости этого клуба успешно синхронизированы", "success")
    except Exception as e:
        flash(f"Ошибка синхронизации гостей: {e}", "error")
    return redirect(url_for("owner.settings"))


@owner_bp.route("/sync/sessions")
@owner_required
def sync_sessions_route():
    try:
        sync_sessions_incremental(_current_club_id())
        flash("Сессии этого клуба успешно синхронизированы", "success")
    except Exception as e:
        flash(f"Ошибка синхронизации сессий: {e}", "error")
    return redirect(url_for("owner.settings"))
