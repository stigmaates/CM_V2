from flask import flash, redirect, render_template, request, session, url_for

from app.core import owner_required, parse_datetime_local
from app.services.clubs import get_club_info
from app.services.wheel import (
    assert_active_wheel_probabilities_sum_is_100,
    create_wheel_prize,
    delete_wheel_prize,
    get_wheel_prize_by_id,
    get_wheel_prizes_for_admin,
    get_wheel_settings_for_admin,
    save_wheel_settings,
    update_wheel_prize,
)

from . import owner_bp


@owner_bp.route('/wheel', methods=['GET', 'POST'])
@owner_required
def wheel_settings():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    club_id_int = int(club_id)

    if request.method == "POST":
        tokens_start_date_raw = request.form.get("tokens_start_date", "").strip()
        spin_cost_raw = request.form.get("spin_cost", "").strip()
        is_enabled = 1 if request.form.get("is_enabled") == "1" else 0

        if not tokens_start_date_raw:
            flash("Укажи дату начала начисления жетонов", "error")
            return redirect(url_for("owner.settings", tab="wheel"))

        try:
            tokens_start_date = parse_datetime_local(tokens_start_date_raw)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("owner.settings", tab="wheel"))

        try:
            spin_cost = int(spin_cost_raw)
        except ValueError:
            flash("Стоимость прокрута должна быть числом", "error")
            return redirect(url_for("owner.settings", tab="wheel"))

        if spin_cost <= 0:
            flash("Стоимость прокрута должна быть больше 0", "error")
            return redirect(url_for("owner.settings", tab="wheel"))

        try:
            if is_enabled:
                assert_active_wheel_probabilities_sum_is_100(club_id_int)
            save_wheel_settings(
                club_id=club_id_int,
                tokens_start_date=tokens_start_date,
                spin_cost=spin_cost,
                is_enabled=is_enabled,
            )
            flash("Настройки колеса сохранены", "success")
        except Exception as e:
            flash(f"Ошибка сохранения настроек колеса: {e}", "error")

        return redirect(url_for("owner.settings", tab="wheel"))

    return redirect(url_for("owner.settings", tab="wheel"))



PRIZE_ICON_CHOICES = {"🎮", "🏆", "🥤", "🍕", "🍔", "🔥", "💎", "🪙", "🍰", "🍪", "⚽️", "🚗", "🔮", "🎉", "🕓", "🎰", "👕"}


def _parse_prize_icon(raw_value: str) -> str:
    icon = (raw_value or "").strip()
    return icon if icon in PRIZE_ICON_CHOICES else "🎁"

def _parse_bonus_amount(raw_value: str) -> int:
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return 0
    try:
        amount = int(raw_value)
    except ValueError:
        raise ValueError("Количество CM-бонусов должно быть целым числом")
    if amount < 0:
        raise ValueError("Количество CM-бонусов не может быть отрицательным")
    return amount


def _parse_token_amount(raw_value: str) -> int:
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return 0
    try:
        amount = int(raw_value)
    except ValueError:
        raise ValueError("Количество жетонов должно быть целым числом")
    if amount < 0:
        raise ValueError("Количество жетонов не может быть отрицательным")
    return amount


@owner_bp.route('/wheel/prizes/add', methods=['POST'])
@owner_required
def wheel_prize_add():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    club_id_int = int(club_id)

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    icon_emoji = _parse_prize_icon(request.form.get("icon_emoji", ""))
    bonus_amount_raw = request.form.get("bonus_amount", "").strip()
    token_amount_raw = request.form.get("token_amount", "").strip()
    probability_raw = request.form.get("probability", "").strip()
    is_active = 1 if request.form.get("is_active") == "1" else 0

    if not name:
        flash("Укажи название приза", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        probability = float(probability_raw.replace(",", "."))
    except ValueError:
        flash("Вероятность должна быть числом", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    if probability <= 0:
        flash("Вероятность должна быть больше 0", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        bonus_amount = _parse_bonus_amount(bonus_amount_raw)
        token_amount = _parse_token_amount(token_amount_raw)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        sort_order = len(get_wheel_prizes_for_admin(club_id_int)) + 1
        new_id = create_wheel_prize(
            club_id=club_id_int,
            name=name,
            description=description or None,
            image_url=image_url or None,
            icon_emoji=icon_emoji,
            bonus_amount=bonus_amount,
            token_amount=token_amount,
            probability=probability,
            is_active=is_active,
            sort_order=sort_order,
        )
        flash("Приз добавлен", "success")
    except Exception as e:
        flash(f"Ошибка добавления приза: {e}", "error")

    return redirect(url_for("owner.settings", tab="wheel"))


@owner_bp.route('/wheel/prizes/<int:prize_id>/update', methods=['POST'])
@owner_required
def wheel_prize_update(prize_id):
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    club_id_int = int(club_id)

    prize = get_wheel_prize_by_id(prize_id, club_id_int)
    if not prize:
        flash("Приз не найден", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    icon_emoji = _parse_prize_icon(request.form.get("icon_emoji", ""))
    bonus_amount_raw = request.form.get("bonus_amount", "").strip()
    token_amount_raw = request.form.get("token_amount", "").strip()
    probability_raw = request.form.get("probability", "").strip()
    is_active = 1 if request.form.get("is_active") == "1" else 0

    if not name:
        flash("Укажи название приза", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        probability = float(probability_raw.replace(",", "."))
    except ValueError:
        flash("Вероятность должна быть числом", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    if probability <= 0:
        flash("Вероятность должна быть больше 0", "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        bonus_amount = _parse_bonus_amount(bonus_amount_raw)
        token_amount = _parse_token_amount(token_amount_raw)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("owner.settings", tab="wheel"))

    try:
        sort_order = int(prize.get("sort_order") or 0)
        update_wheel_prize(
            prize_id=prize_id,
            club_id=club_id_int,
            name=name,
            description=description or None,
            image_url=image_url or None,
            icon_emoji=icon_emoji,
            bonus_amount=bonus_amount,
            token_amount=token_amount,
            probability=probability,
            is_active=is_active,
            sort_order=sort_order,
        )
        flash("Приз обновлён", "success")
    except Exception as e:
        flash(f"Ошибка обновления приза: {e}", "error")

    return redirect(url_for("owner.settings", tab="wheel"))


@owner_bp.route('/wheel/prizes/<int:prize_id>/delete', methods=['POST'])
@owner_required
def wheel_prize_delete(prize_id):
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    club_id_int = int(club_id)

    try:
        delete_wheel_prize(prize_id, club_id_int)
        flash("Приз удалён", "success")
    except Exception as e:
        flash(f"Ошибка удаления приза: {e}", "error")

    return redirect(url_for("owner.settings", tab="wheel"))
