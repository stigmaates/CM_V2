from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core import login_required, parse_datetime_local
from app.services.clubs import get_club_info
from app.services.missions import (
    build_mission_config_from_form,
    create_club_mission,
    disable_club_mission,
    get_club_missions,
    get_club_missions_all,
    get_mission_template_by_id,
    get_mission_templates,
    reward_text_contains_bonus_quantity,
    update_club_mission,
)


def api_mission_templates():
    return {"data": get_mission_templates()}


def api_club_missions():
    club_id = session.get("club_id")
    return {"data": get_club_missions(int(club_id))}


def api_create_mission():
    club_id = session.get("club_id")
    data = request.json or {}
    rt = (data.get("reward_text") or "").strip()
    if reward_text_contains_bonus_quantity(rt):
        return jsonify({"ok": False, "error": "В поле «Приз» нельзя указывать количество бонусов — используйте поле CM-бонусов."}), 400

    create_club_mission(
        club_id=int(club_id),
        mission_template_id=data.get("mission_template_id"),
        target_amount=data.get("target_amount"),
        start_at=parse_datetime_local(data.get("start_at")) if data.get("start_at") else None,
        end_at=parse_datetime_local(data.get("end_at")) if data.get("end_at") else None,
        config=data.get("config"),
        reward_text=data.get("reward_text"),
        custom_name=data.get("custom_name"),
        token_reward=int(data.get("token_reward") or 0),
        cm_bonus_reward=int(data.get("cm_bonus_reward") or 0),
    )
    return {"ok": True}


def api_update_mission(mission_id):
    club_id = session.get("club_id")
    data = request.json or {}
    rt = (data.get("reward_text") or "").strip()
    if reward_text_contains_bonus_quantity(rt):
        return jsonify({"ok": False, "error": "В поле «Приз» нельзя указывать количество бонусов — используйте поле CM-бонусов."}), 400

    update_club_mission(
        mission_id=mission_id,
        club_id=int(club_id),
        target_amount=data.get("target_amount"),
        start_at=parse_datetime_local(data.get("start_at")) if data.get("start_at") else None,
        end_at=parse_datetime_local(data.get("end_at")) if data.get("end_at") else None,
        config=data.get("config"),
        is_enabled=data.get("is_enabled", 1),
        reward_text=data.get("reward_text"),
        custom_name=data.get("custom_name"),
        token_reward=int(data.get("token_reward") or 0),
        cm_bonus_reward=int(data.get("cm_bonus_reward") or 0),
    )
    return {"ok": True}


def api_delete_mission(mission_id):
    club_id = session.get("club_id")
    disable_club_mission(mission_id, int(club_id))
    return {"ok": True}


def missions():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    return render_template(
        "missions.html",
        club=get_club_info(club_id),
        templates=get_mission_templates(),
        missions=get_club_missions_all(int(club_id)),
    )


def missions_add():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    template_id = request.form.get("mission_template_id", "").strip()
    target_amount = request.form.get("target_amount", "").strip()
    start_at_raw = request.form.get("start_at", "").strip()
    end_at_raw = request.form.get("end_at", "").strip()
    custom_name = request.form.get("custom_name", "").strip()
    reward_text = request.form.get("reward_text", "").strip()
    token_reward_raw = request.form.get("token_reward", "0").strip() or "0"
    cm_bonus_reward_raw = request.form.get("cm_bonus_reward", "0").strip() or "0"

    if not template_id or not target_amount:
        flash("Выбери шаблон и укажи целевое значение", "error")
        return redirect(url_for("missions"))

    try:
        template_id = int(template_id)
        target_amount = int(target_amount)
        token_reward = int(token_reward_raw)
        cm_bonus_reward = int(cm_bonus_reward_raw)
        start_at = parse_datetime_local(start_at_raw) if start_at_raw else None
        end_at = parse_datetime_local(end_at_raw) if end_at_raw else None
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("missions"))

    if target_amount <= 0:
        flash("Целевое значение должно быть больше 0", "error")
        return redirect(url_for("missions"))

    if token_reward < 0:
        flash("Количество жетонов не может быть отрицательным", "error")
        return redirect(url_for("missions"))

    if cm_bonus_reward < 0:
        flash("Количество CM-бонусов не может быть отрицательным", "error")
        return redirect(url_for("missions"))

    if reward_text_contains_bonus_quantity(reward_text):
        flash(
            "В поле «Приз» нельзя указывать количество бонусов: для CM-бонусов есть отдельное поле ниже.",
            "error",
        )
        return redirect(url_for("missions"))

    template = get_mission_template_by_id(template_id)
    if not template:
        flash("Шаблон задания не найден", "error")
        return redirect(url_for("missions"))

    try:
        config = build_mission_config_from_form(template, request.form)
        create_club_mission(
            club_id=int(club_id),
            mission_template_id=template_id,
            target_amount=target_amount,
            start_at=start_at,
            end_at=end_at,
            config=config,
            reward_text=reward_text,
            custom_name=custom_name,
            token_reward=token_reward,
            cm_bonus_reward=cm_bonus_reward,
        )
        flash("Задание добавлено", "success")
    except Exception as e:
        flash(f"Ошибка добавления задания: {e}", "error")

    return redirect(url_for("missions"))


def missions_update(mission_id):
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    template_id = request.form.get("mission_template_id", "").strip()
    target_amount = request.form.get("target_amount", "").strip()
    start_at_raw = request.form.get("start_at", "").strip()
    end_at_raw = request.form.get("end_at", "").strip()
    custom_name = request.form.get("custom_name", "").strip()
    reward_text = request.form.get("reward_text", "").strip()
    token_reward_raw = request.form.get("token_reward", "0").strip() or "0"
    cm_bonus_reward_raw = request.form.get("cm_bonus_reward", "0").strip() or "0"
    is_enabled = 1 if request.form.get("is_enabled") == "1" else 0

    if not template_id or not target_amount:
        flash("Не хватает данных для обновления", "error")
        return redirect(url_for("missions"))

    try:
        template_id = int(template_id)
        target_amount = int(target_amount)
        token_reward = int(token_reward_raw)
        cm_bonus_reward = int(cm_bonus_reward_raw)
        start_at = parse_datetime_local(start_at_raw) if start_at_raw else None
        end_at = parse_datetime_local(end_at_raw) if end_at_raw else None
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("missions"))

    if target_amount <= 0:
        flash("Целевое значение должно быть больше 0", "error")
        return redirect(url_for("missions"))

    if token_reward < 0:
        flash("Количество жетонов не может быть отрицательным", "error")
        return redirect(url_for("missions"))

    if cm_bonus_reward < 0:
        flash("Количество CM-бонусов не может быть отрицательным", "error")
        return redirect(url_for("missions"))

    if reward_text_contains_bonus_quantity(reward_text):
        flash(
            "В поле «Приз» нельзя указывать количество бонусов: для CM-бонусов есть отдельное поле ниже.",
            "error",
        )
        return redirect(url_for("missions"))

    template = get_mission_template_by_id(template_id)
    if not template:
        flash("Шаблон задания не найден", "error")
        return redirect(url_for("missions"))

    try:
        config = build_mission_config_from_form(template, request.form)
        update_club_mission(
            mission_id=mission_id,
            club_id=int(club_id),
            target_amount=target_amount,
            start_at=start_at,
            end_at=end_at,
            config=config,
            is_enabled=is_enabled,
            reward_text=reward_text,
            custom_name=custom_name,
            token_reward=token_reward,
            cm_bonus_reward=cm_bonus_reward,
        )
        flash("Задание обновлено", "success")
    except Exception as e:
        flash(f"Ошибка обновления задания: {e}", "error")

    return redirect(url_for("missions"))


def missions_disable(mission_id):
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("club_create"))

    try:
        disable_club_mission(mission_id, int(club_id))
        flash("Задание отключено", "success")
    except Exception as e:
        flash(f"Ошибка отключения задания: {e}", "error")

    return redirect(url_for("missions"))


def register_mission_routes(app):
    app.add_url_rule('/api/missions/templates', view_func=login_required(api_mission_templates))
    app.add_url_rule('/api/missions', view_func=login_required(api_club_missions))
    app.add_url_rule('/api/missions', view_func=login_required(api_create_mission), methods=['POST'])
    app.add_url_rule('/api/missions/<int:mission_id>', view_func=login_required(api_update_mission), methods=['PUT'])
    app.add_url_rule('/api/missions/<int:mission_id>', view_func=login_required(api_delete_mission), methods=['DELETE'])
    app.add_url_rule('/missions', view_func=login_required(missions))
    app.add_url_rule('/missions/add', view_func=login_required(missions_add), methods=['POST'])
    app.add_url_rule('/missions/<int:mission_id>/update', view_func=login_required(missions_update), methods=['POST'])
    app.add_url_rule('/missions/<int:mission_id>/disable', view_func=login_required(missions_disable), methods=['POST'])
