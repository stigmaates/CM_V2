from flask import flash, redirect, request, session, url_for

from app.core import owner_required
from app.services.audit import record_audit_event
from app.services.game_contracts import (
    GameContractError,
    create_contract_template,
    delete_contract_template,
    disable_contract_template,
    update_contract_template,
)

from . import owner_bp


def _template_payload() -> dict:
    conditions = {}
    for key in ("weapon", "map", "hero_id"):
        value = request.form.get(key, "").strip()
        if value:
            conditions[key] = value
    return {
        "game": request.form.get("game"),
        "title": request.form.get("title"),
        "description_template": request.form.get("description_template"),
        "metric_type": request.form.get("metric_type"),
        "target_value": request.form.get("target_value"),
        "period_type": request.form.get("period_type"),
        "difficulty": request.form.get("difficulty"),
        "reward_tokens": request.form.get("reward_tokens"),
        "reward_bonus": request.form.get("reward_bonus"),
        "weight": request.form.get("weight"),
        "conditions": conditions,
        "weapon": conditions.get("weapon"),
        "map": conditions.get("map"),
        "hero_id": conditions.get("hero_id"),
        "is_active": request.form.get("is_active", "0"),
    }


@owner_bp.route("/contracts", methods=["POST"])
@owner_required
def contracts_create():
    club_id = int(session["club_id"])
    try:
        template_id = create_contract_template(club_id, _template_payload())
        record_audit_event(
            action="owner.game_contract.create",
            club_id=club_id,
            entity_type="game_contract_template",
            entity_id=template_id,
        )
        flash("Шаблон игрового контракта создан", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("Не удалось создать шаблон контракта", "error")
    return redirect(url_for("owner.settings", tab="contracts"))


@owner_bp.route("/contracts/<int:template_id>", methods=["POST"])
@owner_required
def contracts_update(template_id: int):
    club_id = int(session["club_id"])
    try:
        update_contract_template(club_id, template_id, _template_payload())
        record_audit_event(
            action="owner.game_contract.update",
            club_id=club_id,
            entity_type="game_contract_template",
            entity_id=template_id,
        )
        flash("Шаблон контракта сохранён", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("Не удалось сохранить шаблон контракта", "error")
    return redirect(url_for("owner.settings", tab="contracts") + f"#contract-{template_id}")


@owner_bp.route("/contracts/<int:template_id>/disable", methods=["POST"])
@owner_required
def contracts_disable(template_id: int):
    club_id = int(session["club_id"])
    disable_contract_template(club_id, template_id)
    record_audit_event(
        action="owner.game_contract.disable",
        club_id=club_id,
        entity_type="game_contract_template",
        entity_id=template_id,
    )
    flash("Шаблон выключен. Уже выданные контракты продолжат работать", "success")
    return redirect(url_for("owner.settings", tab="contracts"))


@owner_bp.route("/contracts/<int:template_id>/delete", methods=["POST"])
@owner_required
def contracts_delete(template_id: int):
    club_id = int(session["club_id"])
    try:
        delete_contract_template(club_id, template_id)
        record_audit_event(
            action="owner.game_contract.delete",
            club_id=club_id,
            entity_type="game_contract_template",
            entity_id=template_id,
        )
        flash("Шаблон контракта удалён", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    return redirect(url_for("owner.settings", tab="contracts"))
