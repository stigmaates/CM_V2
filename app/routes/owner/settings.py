from flask import flash, redirect, render_template, request, session, url_for

from app.core import owner_required
from app.services.clubs import get_club_info, update_club_info
from app.services.missions import get_club_missions_all, get_mission_templates
from app.services.wheel import get_wheel_prizes_for_admin, get_wheel_settings_for_admin
from app.services.pc_heatmap import get_pc_name_settings, save_pc_name_settings
from app.services.system_status import get_owner_settings_system_status

from . import owner_bp


SETTINGS_TABS = {"club", "missions", "wheel"}


@owner_bp.route("/settings/pc-names", methods=["POST"])
@owner_required
def settings_pc_names_save():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    uuids = request.form.getlist("pc_uuid")
    names = request.form.getlist("pc_name")
    orders = request.form.getlist("pc_sort_order")

    items = []
    for idx, uuid in enumerate(uuids):
        items.append({
            "uuid": uuid,
            "display_name": names[idx] if idx < len(names) else "",
            "sort_order": orders[idx] if idx < len(orders) else (idx + 1) * 10,
        })

    try:
        save_pc_name_settings(int(club_id), items)
        flash("Названия ПК сохранены", "success")
    except Exception as exc:
        flash(f"Ошибка сохранения ПК: {exc}", "error")

    return redirect(url_for("owner.settings", tab="club") + "#pc-names")


@owner_bp.route("/settings", methods=["GET", "POST"])
@owner_required
def settings():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    active_tab = request.args.get("tab", "club").strip()
    if active_tab not in SETTINGS_TABS:
        active_tab = "club"

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        lg_api_key = request.form.get("lg_api_key", "").strip()
        secret = request.form.get("secret", "").strip()
        cm_bonus_admin_chat_id = request.form.get("cm_bonus_admin_chat_id", "").strip()
        instagram_url = request.form.get("instagram_url", "").strip()
        youtube_url = request.form.get("youtube_url", "").strip()
        vk_url = request.form.get("vk_url", "").strip()
        telegram_channel_url = request.form.get("telegram_channel_url", "").strip()
        yandex_maps_url = request.form.get("yandex_maps_url", "").strip()
        two_gis_url = request.form.get("two_gis_url", "").strip()

        if not name or not lg_api_key or not secret:
            flash("Заполни все поля", "error")
            return redirect(url_for("owner.settings", tab="club"))

        try:
            update_club_info(club_id, name, lg_api_key, secret, cm_bonus_admin_chat_id, instagram_url, youtube_url, vk_url, telegram_channel_url, yandex_maps_url, two_gis_url)
            session["club_name"] = name
            flash("Настройки клуба обновлены", "success")
            return redirect(url_for("owner.settings", tab="club"))
        except Exception as e:
            flash(f"Ошибка обновления настроек: {e}", "error")
            return redirect(url_for("owner.settings", tab="club"))

    club_id_int = int(club_id)
    context = {
        "club": get_club_info(club_id),
        "active_tab": active_tab,
    }

    if active_tab == "club":
        context.update({
            "pc_name_settings": get_pc_name_settings(club_id_int),
            "system_status": get_owner_settings_system_status(club_id_int),
        })

    if active_tab == "missions":
        context.update({
            "templates": get_mission_templates(),
            "missions": get_club_missions_all(club_id_int),
        })
    elif active_tab == "wheel":
        prizes = get_wheel_prizes_for_admin(club_id_int)
        wheel_active_prob_sum = sum(
            float(p.get("probability") or 0) for p in prizes if int(p.get("is_active") or 0)
        )
        context.update({
            "wheel_settings": get_wheel_settings_for_admin(club_id_int),
            "prizes": prizes,
            "wheel_active_prob_sum": wheel_active_prob_sum,
            "prize_icon_choices": ['🎮','🏆','🥤','🍕','🍔','🔥','💎','🪙','🍰','🍪','⚽️','🚗','🔮','🎉','🕓','🎰','👕'],
        })

    return render_template("owner/settings.html", **context)
