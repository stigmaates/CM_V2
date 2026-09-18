from flask import flash, redirect, request, session, url_for

from app.core import owner_required
from app.services.audit import record_audit_event
from app.services.game_contracts import GameContractError, save_contract_reward_settings

from . import owner_bp


@owner_bp.route("/contracts/rewards", methods=["POST"])
@owner_required
def contract_rewards_save():
    club_id = int(session["club_id"])
    is_enabled = request.form.get("contracts_enabled") == "1"
    values = {
        difficulty: {
            "reward_tokens": request.form.get(f"{difficulty}_reward_tokens", "0"),
            "reward_bonus": request.form.get(f"{difficulty}_reward_bonus", "0"),
        }
        for difficulty in ("easy", "medium", "hard")
    }
    try:
        save_contract_reward_settings(club_id, values, is_enabled=is_enabled)
        record_audit_event(
            action="owner.game_contract_settings.update",
            club_id=club_id,
            entity_type="game_contract_settings",
            details={"is_enabled": is_enabled, "rewards": values},
        )
        flash("Настройки игровых контрактов сохранены", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("Не удалось сохранить награды за контракты", "error")
    return redirect(url_for("owner.settings", tab="contracts"))
