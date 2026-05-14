from flask import flash, redirect, render_template, request, session, url_for

from app.core import login_required
from app.services.clubs import get_club_info, update_club_info


def settings():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        lg_api_key = request.form.get("lg_api_key", "").strip()
        secret = request.form.get("secret", "").strip()
        cm_bonus_admin_chat_id = request.form.get("cm_bonus_admin_chat_id", "").strip()

        if not name or not lg_api_key or not secret:
            flash("Заполни все поля", "error")
            return redirect(url_for("settings"))

        try:
            update_club_info(club_id, name, lg_api_key, secret, cm_bonus_admin_chat_id)
            flash("Настройки клуба обновлены", "success")
            return redirect(url_for("settings"))
        except Exception as e:
            flash(f"Ошибка обновления настроек: {e}", "error")
            return redirect(url_for("settings"))

    club = get_club_info(club_id)
    return render_template("settings.html", club=club)


def register_settings_routes(app):
    app.add_url_rule('/settings', view_func=login_required(settings), methods=['GET', 'POST'])
