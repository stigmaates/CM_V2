from flask import flash, redirect, render_template, request, session, url_for

from app.config import TOPUP_BONUS_MAX_AMOUNT
from app.core import OWNER_ACCESS_ROLES, owner_required
from app.services.audit import record_audit_event
from app.services.cases import get_cases_for_admin, get_game_mode
from app.services.clubs import get_club_info, update_club_info
from app.services.guest_management import (
    adjust_guest_balance,
    get_owner_guest_lookup,
    set_guest_module_ban,
)
from app.services.missions import get_club_missions_all, get_mission_templates
from app.services.owner_profile import get_owner_profile, update_owner_profile
from app.services.pc_heatmap import get_pc_name_settings, save_pc_name_settings
from app.services.system_status import get_owner_settings_system_status
from app.services.test_guests import ensure_test_guest
from app.services.topup_bonuses import (
    TOPUP_BONUS_VARIABLES,
    get_topup_bonus_settings,
    get_welcome_reward_settings,
    save_topup_bonus_settings,
    save_welcome_reward_settings,
)
from app.services.upload_storage import get_club_upload_usage_info
from app.services.wheel import get_wheel_prizes_for_admin, get_wheel_settings_for_admin

from . import owner_bp

SETTINGS_TABS = {"club", "missions", "wheel", "profile", "guests"}
BONUS_EDITORS = {"wheel", "cases"}


@owner_bp.route("/settings/profile", methods=["POST"])
@owner_required
def settings_profile_save():
    if session.get("role") not in OWNER_ACCESS_ROLES:
        flash("Профиль недоступен в режиме просмотра от администратора", "error")
        return redirect(url_for("owner.settings", tab="club"))

    user_id = session.get("user_id")
    club_id = session.get("club_id")
    if not user_id or not club_id:
        flash("Профиль владельца не найден", "error")
        return redirect(url_for("owner.settings", tab="profile"))

    name = request.form.get("name", "")
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    if new_password != new_password_confirm:
        flash("Новые пароли не совпадают", "error")
        return redirect(url_for("owner.settings", tab="profile"))

    try:
        result = update_owner_profile(
            user_id=int(user_id),
            club_id=int(club_id),
            name=name,
            current_password=current_password,
            new_password=new_password,
        )
        session["name"] = result["name"]
        record_audit_event(
            action="owner.profile.update",
            club_id=int(club_id),
            entity_type="user",
            entity_id=int(user_id),
            details={"name_changed": True, "password_changed": result["password_changed"]},
        )
        flash("Профиль обновлён", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception as exc:
        flash(f"Ошибка обновления профиля: {exc}", "error")

    return redirect(url_for("owner.settings", tab="profile"))


def _guest_management_redirect(phone: str = ""):
    return redirect(url_for("owner.settings", tab="guests", phone=(phone or "").strip()))


@owner_bp.route("/settings/guests/adjust", methods=["POST"])
@owner_required
def settings_guest_balance_adjust():
    if session.get("role") not in OWNER_ACCESS_ROLES:
        flash("Управление гостями недоступно в режиме просмотра от администратора", "error")
        return redirect(url_for("owner.settings", tab="club"))

    phone = request.form.get("phone", "")
    try:
        club_id = int(session["club_id"])
        user_id = int(session["user_id"])
        guest_id = int(request.form.get("guest_id") or 0)
        amount = int(request.form.get("amount") or 0)
        operation = request.form.get("operation", "add")
        if amount <= 0:
            raise ValueError("Укажите положительную сумму")
        if operation not in {"add", "subtract"}:
            raise ValueError("Неизвестная операция")
        signed_amount = amount if operation == "add" else -amount
        result = adjust_guest_balance(
            club_id=club_id,
            guest_id=guest_id,
            balance_type=request.form.get("balance_type", ""),
            amount=signed_amount,
            actor_user_id=user_id,
            reason=request.form.get("reason", ""),
        )
        record_audit_event(
            action="owner.guest.balance_adjust",
            club_id=club_id,
            entity_type="guest",
            entity_id=guest_id,
            details={
                "balance_type": result["balance_type"],
                "amount": result["amount"],
                "description": result["description"],
            },
        )
        flash("Баланс гостя обновлён", "success")
    except (KeyError, TypeError, ValueError) as exc:
        flash(str(exc) or "Некорректные данные", "error")
    except Exception as exc:
        flash(f"Не удалось изменить баланс: {exc}", "error")
    return _guest_management_redirect(phone)


@owner_bp.route("/settings/guests/access", methods=["POST"])
@owner_required
def settings_guest_access_update():
    if session.get("role") not in OWNER_ACCESS_ROLES:
        flash("Управление гостями недоступно в режиме просмотра от администратора", "error")
        return redirect(url_for("owner.settings", tab="club"))

    phone = request.form.get("phone", "")
    try:
        club_id = int(session["club_id"])
        user_id = int(session["user_id"])
        guest_id = int(request.form.get("guest_id") or 0)
        action = request.form.get("action", "")
        if action not in {"ban", "unban"}:
            raise ValueError("Неизвестное действие")
        is_banned = action == "ban"
        result = set_guest_module_ban(
            club_id=club_id,
            guest_id=guest_id,
            is_banned=is_banned,
            actor_user_id=user_id,
            reason=request.form.get("reason", ""),
        )
        record_audit_event(
            action="owner.guest.ban" if is_banned else "owner.guest.unban",
            club_id=club_id,
            entity_type="guest",
            entity_id=guest_id,
            details={"reason": result["reason"]},
        )
        flash("Доступ гостя заблокирован" if is_banned else "Доступ гостя восстановлен", "success")
    except (KeyError, TypeError, ValueError) as exc:
        flash(str(exc) or "Некорректные данные", "error")
    except Exception as exc:
        flash(f"Не удалось изменить доступ: {exc}", "error")
    return _guest_management_redirect(phone)


@owner_bp.route("/settings/topup-bonuses", methods=["POST"])
@owner_required
def settings_topup_bonuses_save():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    is_enabled = request.form.get("is_enabled") == "1"
    message_template = request.form.get("message_template", "")
    min_amounts = request.form.getlist("min_amount")
    bonus_amounts = request.form.getlist("bonus_amount")
    reward_types = request.form.getlist("reward_type")
    rules = []
    try:
        for index, raw_min_amount in enumerate(min_amounts):
            raw_bonus_amount = bonus_amounts[index] if index < len(bonus_amounts) else ""
            reward_type = reward_types[index] if index < len(reward_types) else "cm_bonus"
            if not raw_min_amount.strip() and not raw_bonus_amount.strip():
                continue
            rules.append(
                {
                    "min_amount": raw_min_amount.replace(",", "."),
                    "bonus_amount": int(raw_bonus_amount),
                    "reward_type": reward_type,
                }
            )
        save_topup_bonus_settings(
            int(club_id),
            is_enabled=is_enabled,
            message_template=message_template,
            rules=rules,
        )
        record_audit_event(
            action="owner.topup_bonus_settings.update",
            club_id=int(club_id),
            entity_type="club_topup_bonus_settings",
            entity_id=club_id,
            details={
                "is_enabled": is_enabled,
                "rules_count": len(rules),
            },
        )
        flash("Бонусы за пополнения сохранены", "success")
    except (TypeError, ValueError) as exc:
        flash(f"Не удалось сохранить правила: {exc}", "error")
    except Exception as exc:
        flash(f"Ошибка сохранения бонусов за пополнения: {exc}", "error")

    return redirect(url_for("owner.settings", tab="wheel") + "#topup-bonuses")


@owner_bp.route("/settings/welcome-reward", methods=["POST"])
@owner_required
def settings_welcome_reward_save():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    is_enabled = request.form.get("is_enabled") == "1"
    cm_bonus_enabled = request.form.get("cm_bonus_enabled") == "1"
    token_enabled = request.form.get("token_enabled") == "1"
    try:
        cm_bonus_amount = int(request.form.get("cm_bonus_amount") or 0) if cm_bonus_enabled else 0
        token_amount = int(request.form.get("token_amount") or 0) if token_enabled else 0
        save_welcome_reward_settings(
            int(club_id),
            is_enabled=is_enabled,
            cm_bonus_amount=cm_bonus_amount,
            token_amount=token_amount,
        )
        record_audit_event(
            action="owner.welcome_reward_settings.update",
            club_id=int(club_id),
            entity_type="club_topup_bonus_settings",
            entity_id=club_id,
            details={
                "is_enabled": is_enabled,
                "cm_bonus_amount": cm_bonus_amount,
                "token_amount": token_amount,
            },
        )
        flash("Приветственная награда сохранена", "success")
    except (TypeError, ValueError) as exc:
        flash(f"Не удалось сохранить приветственную награду: {exc}", "error")
    except Exception as exc:
        flash(f"Ошибка сохранения приветственной награды: {exc}", "error")

    return redirect(url_for("owner.settings", tab="wheel") + "#welcome-reward")


@owner_bp.route("/settings/guest-test", methods=["POST"])
@owner_required
def guest_test_mode_start():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return redirect(url_for("owner.club_create"))

    club = get_club_info(club_id)
    if not club:
        flash("Клуб не найден", "error")
        return redirect(url_for("owner.settings", tab="club"))

    club_id_int = int(club_id)
    guest = ensure_test_guest(club_id_int, club.get("name") if isinstance(club, dict) else getattr(club, "name", None))
    session["guest_id"] = guest["guest_id"]
    session["guest_club_id"] = guest["club_id"]
    session["guest_name"] = guest["fio"]
    session["guest_telegram_id"] = None
    session["guest_logged_in"] = True
    session["guest_test_mode"] = True
    session["guest_test_label"] = f"Тестовый вход владельца · клуб {guest['club_id']}"
    session["guest_test_source"] = "owner_settings"
    session["guest_test_return_label"] = "Выйти из режима"

    record_audit_event(
        action="owner.guest_test.start",
        club_id=club_id_int,
        entity_type="guest",
        entity_id=guest["guest_id"],
        details={"test_mode": True},
    )

    return redirect(url_for("guest.dashboard"))


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
        items.append(
            {
                "uuid": uuid,
                "display_name": names[idx] if idx < len(names) else "",
                "sort_order": orders[idx] if idx < len(orders) else (idx + 1) * 10,
            }
        )

    try:
        save_pc_name_settings(int(club_id), items)
        record_audit_event(
            action="owner.pc_names.update",
            club_id=int(club_id),
            entity_type="club_pc_names",
            details={"items_count": len(items)},
        )
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
    if active_tab in {"profile", "guests"} and session.get("role") not in OWNER_ACCESS_ROLES:
        flash("Раздел недоступен в режиме просмотра от администратора", "error")
        return redirect(url_for("owner.settings", tab="club"))
    bonus_editor = request.args.get("editor", "wheel").strip()
    if bonus_editor not in BONUS_EDITORS:
        bonus_editor = "wheel"

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
            update_club_info(
                club_id,
                name,
                lg_api_key,
                secret,
                cm_bonus_admin_chat_id,
                instagram_url,
                youtube_url,
                vk_url,
                telegram_channel_url,
                yandex_maps_url,
                two_gis_url,
            )
            session["club_name"] = name
            record_audit_event(
                action="owner.club_settings.update",
                club_id=int(club_id),
                entity_type="club",
                entity_id=club_id,
                details={
                    "name": name,
                    "has_lg_api_key": bool(lg_api_key),
                    "has_secret": bool(secret),
                    "has_bonus_admin_chat": bool(cm_bonus_admin_chat_id),
                    "social_links": {
                        "instagram": bool(instagram_url),
                        "youtube": bool(youtube_url),
                        "vk": bool(vk_url),
                        "telegram": bool(telegram_channel_url),
                        "yandex_maps": bool(yandex_maps_url),
                        "two_gis": bool(two_gis_url),
                    },
                },
            )
            flash("Настройки клуба обновлены", "success")
            return redirect(url_for("owner.settings", tab="club"))
        except Exception as e:
            flash(f"Ошибка обновления настроек: {e}", "error")
            return redirect(url_for("owner.settings", tab="club"))

    club_id_int = int(club_id)
    context = {
        "club": get_club_info(club_id),
        "active_tab": active_tab,
        "guest_login_url": url_for("guest.login", club_id=club_id_int, _external=True),
    }

    if active_tab == "profile":
        profile_user = get_owner_profile(int(session["user_id"]), club_id_int)
        if not profile_user:
            flash("Профиль владельца не найден", "error")
            return redirect(url_for("owner.settings", tab="club"))
        context["profile_user"] = profile_user

    if active_tab == "guests":
        phone = request.args.get("phone", "").strip()
        context["guest_management_phone"] = phone
        context["guest_lookup"] = None
        if phone:
            try:
                context["guest_lookup"] = get_owner_guest_lookup(club_id=club_id_int, phone=phone)
            except Exception as exc:
                flash(f"Не удалось загрузить данные гостя: {exc}", "error")

    if active_tab == "club":
        context.update(
            {
                "pc_name_settings": get_pc_name_settings(club_id_int),
                "system_status": get_owner_settings_system_status(club_id_int),
            }
        )

    if active_tab == "missions":
        cases = get_cases_for_admin(club_id_int)
        context.update(
            {
                "templates": get_mission_templates(),
                "missions": get_club_missions_all(club_id_int),
                "active_cases": [case for case in cases if int(case.get("is_active") or 0)],
            }
        )
    elif active_tab == "wheel":
        prizes = get_wheel_prizes_for_admin(club_id_int)
        wheel_active_prob_sum = sum(float(p.get("probability") or 0) for p in prizes if int(p.get("is_active") or 0))
        context.update(
            {
                "wheel_settings": get_wheel_settings_for_admin(club_id_int),
                "prizes": prizes,
                "wheel_active_prob_sum": wheel_active_prob_sum,
                "prize_icon_choices": [
                    "🎮",
                    "🏆",
                    "🥤",
                    "🍕",
                    "🍔",
                    "🔥",
                    "💎",
                    "🪙",
                    "🍰",
                    "🍪",
                    "⚽️",
                    "🚗",
                    "🔮",
                    "🎉",
                    "🕓",
                    "🎰",
                    "👕",
                ],
                "game_mode": get_game_mode(club_id_int),
                "bonus_editor": bonus_editor,
                "cases": get_cases_for_admin(club_id_int),
                "case_upload_usage": get_club_upload_usage_info(club_id_int),
                "topup_bonus_settings": get_topup_bonus_settings(club_id_int),
                "welcome_reward_settings": get_welcome_reward_settings(club_id_int),
                "topup_bonus_variables": TOPUP_BONUS_VARIABLES,
                "topup_bonus_exclude_from_amount": TOPUP_BONUS_MAX_AMOUNT,
                "topup_bonus_max_rule_amount": TOPUP_BONUS_MAX_AMOUNT - 0.01,
            }
        )

    return render_template("owner/settings.html", **context)
