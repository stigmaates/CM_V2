from flask import flash, redirect, request, session, url_for

from app.core import owner_required
from app.services.audit import record_audit_event
from app.services.game_contracts import GameContractError, save_contract_reward_settings

from . import owner_bp


@owner_bp.route("/contracts/rewards", methods=["POST"])
@owner_required
def contract_rewards_save():
    club_id = int(session["club_id"])
    values = {
        difficulty: {
            "reward_tokens": request.form.get(f"{difficulty}_reward_tokens", "0"),
            "reward_bonus": request.form.get(f"{difficulty}_reward_bonus", "0"),
        }
        for difficulty in ("easy", "medium", "hard")
    }
    try:
        save_contract_reward_settings(club_id, values)
        record_audit_event(
            action="owner.game_contract_rewards.update",
            club_id=club_id,
            entity_type="game_contract_reward_settings",
            details=values,
        )
        flash("Награды за игровые контракты сохранены", "success")
    except GameContractError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("Не удалось сохранить награды за контракты", "error")
    return redirect(url_for("owner.settings", tab="contracts"))
