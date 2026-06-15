from flask import flash, redirect, request, session, url_for

from app.core import owner_required
from app.services.cases import (
    assert_case_active_items_probability_sum_is_100,
    create_case,
    create_case_item,
    delete_case,
    delete_case_item,
    get_case_by_id,
    get_case_item_by_id,
    get_cases_for_admin,
    save_game_mode,
    update_case,
    update_case_item,
)
from app.services.upload_storage import (
    UploadError,
    delete_local_upload,
    has_uploaded_file,
    save_uploaded_case_image,
    validate_external_image_url,
)

from . import owner_bp


def _redirect_wheel():
    return redirect(url_for("owner.settings", tab="wheel"))


def _require_club_id():
    club_id = session.get("club_id")
    if not club_id:
        flash("Сначала создайте клуб", "error")
        return None
    return int(club_id)


def _parse_int(raw_value: str, field_name: str, allow_negative: bool = False) -> int:
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return 0
    try:
        value = int(raw_value)
    except ValueError:
        raise ValueError(f"{field_name} должно быть целым числом")
    if not allow_negative and value < 0:
        raise ValueError(f"{field_name} не может быть отрицательным")
    return value


def _parse_probability(raw_value: str) -> float:
    raw_value = (raw_value or "").strip()
    try:
        probability = float(raw_value.replace(",", "."))
    except ValueError:
        raise ValueError("Шанс выпадения должен быть числом")
    if probability <= 0:
        raise ValueError("Шанс выпадения должен быть больше 0")
    return probability


CASE_RARITY_LABELS = ("Обычный", "Редкий", "Очень редкий", "Ультра редкий")


def _parse_rarity_label(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if value not in CASE_RARITY_LABELS:
        return "Обычный"
    return value


def _get_uploaded_image_url(*, club_id: int, kind: str, existing_url: str | None = None) -> str | None:
    """Return final image_url based on uploaded file / external URL / remove checkbox."""
    file = request.files.get("image_file")
    remove_image = request.form.get("remove_image") == "1"
    raw_url = request.form.get("image_url", "").strip()

    if has_uploaded_file(file):
        return save_uploaded_case_image(
            club_id=club_id,
            kind=kind,
            file=file,
            replacing_url=existing_url,
        )

    if remove_image:
        return None

    return validate_external_image_url(raw_url)


def _delete_old_image_if_replaced(old_url: str | None, new_url: str | None):
    if old_url and old_url != new_url:
        delete_local_upload(old_url)


def _delete_case_images_after_delete(case_id: int, club_id: int):
    """Best-effort deletion of locally uploaded case cover and item images."""
    case_images = []
    try:
        for case in get_cases_for_admin(club_id):
            if int(case.get("id") or 0) != int(case_id):
                continue
            case_images.append(case.get("image_url"))
            for item in case.get("items") or []:
                case_images.append(item.get("image_url"))
            break
    except Exception:
        return []

    return [url for url in case_images if url]


@owner_bp.route('/game-mode', methods=['POST'])
@owner_required
def game_mode_save():
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    mode = request.form.get("game_mode", "wheel").strip()
    try:
        save_game_mode(club_id, mode)
        flash("Режим бонусной игры сохранён", "success")
    except Exception as e:
        flash(f"Ошибка сохранения режима: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/add', methods=['POST'])
@owner_required
def case_add():
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    badge_label = request.form.get("badge_label", "").strip()
    price_raw = request.form.get("price_tokens", "").strip()

    if not name:
        flash("Укажи название кейса", "error")
        return _redirect_wheel()

    try:
        price_tokens = _parse_int(price_raw, "Цена в жетонах")
        image_url = _get_uploaded_image_url(club_id=club_id, kind="case_cover")
    except (ValueError, UploadError) as e:
        flash(str(e), "error")
        return _redirect_wheel()

    try:
        sort_order = len(get_cases_for_admin(club_id)) + 1
        create_case(
            club_id=club_id,
            name=name,
            description=description or None,
            image_url=image_url,
            badge_label=badge_label or None,
            price_tokens=price_tokens,
            is_active=0,
            sort_order=sort_order,
        )
        flash("Кейс добавлен. Добавь предметы и проценты выпадения, затем включи кейс.", "success")
    except Exception as e:
        delete_local_upload(image_url)
        flash(f"Ошибка добавления кейса: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/<int:case_id>/update', methods=['POST'])
@owner_required
def case_update(case_id):
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    case = get_case_by_id(case_id, club_id)
    if not case:
        flash("Кейс не найден", "error")
        return _redirect_wheel()

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    badge_label = request.form.get("badge_label", "").strip()
    price_raw = request.form.get("price_tokens", "").strip()
    is_active = 1 if request.form.get("is_active") == "1" else 0

    if not name:
        flash("Укажи название кейса", "error")
        return _redirect_wheel()

    old_image_url = case.get("image_url")

    try:
        price_tokens = _parse_int(price_raw, "Цена в жетонах")
        image_url = _get_uploaded_image_url(
            club_id=club_id,
            kind="case_cover",
            existing_url=old_image_url,
        )
    except (ValueError, UploadError) as e:
        flash(str(e), "error")
        return _redirect_wheel()

    try:
        update_case(
            case_id=case_id,
            club_id=club_id,
            name=name,
            description=description or None,
            image_url=image_url,
            badge_label=badge_label or None,
            price_tokens=price_tokens,
            is_active=is_active,
            sort_order=int(case.get("sort_order") or 0),
        )
        _delete_old_image_if_replaced(old_image_url, image_url)
        flash("Кейс обновлён", "success")
    except Exception as e:
        # If a new local file was saved but DB update failed, remove it.
        if image_url != old_image_url:
            delete_local_upload(image_url)
        flash(f"Ошибка обновления кейса: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/<int:case_id>/delete', methods=['POST'])
@owner_required
def case_delete(case_id):
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    image_urls = _delete_case_images_after_delete(case_id, club_id)

    try:
        delete_case(case_id, club_id)
        for url in image_urls:
            delete_local_upload(url)
        flash("Кейс удалён", "success")
    except Exception as e:
        flash(f"Ошибка удаления кейса: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/<int:case_id>/items/add', methods=['POST'])
@owner_required
def case_item_add(case_id):
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    case = get_case_by_id(case_id, club_id)
    if not case:
        flash("Кейс не найден", "error")
        return _redirect_wheel()

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    bonus_raw = request.form.get("bonus_amount", "").strip()
    token_raw = request.form.get("token_amount", "").strip()
    probability_raw = request.form.get("probability", "").strip()
    rarity_label = _parse_rarity_label(request.form.get("rarity_label", "Обычный"))
    is_active = 1 if request.form.get("is_active") == "1" else 0

    if not name:
        flash("Укажи название предмета", "error")
        return _redirect_wheel()

    try:
        probability = _parse_probability(probability_raw)
        bonus_amount = _parse_int(bonus_raw, "Количество КБ")
        token_amount = _parse_int(token_raw, "Количество жетонов")
        image_url = _get_uploaded_image_url(club_id=club_id, kind="case_item")
    except (ValueError, UploadError) as e:
        flash(str(e), "error")
        return _redirect_wheel()

    try:
        items = case.get("items") or []
        sort_order = len(items) + 1
        create_case_item(
            case_id=case_id,
            club_id=club_id,
            name=name,
            description=description or None,
            image_url=image_url,
            bonus_amount=bonus_amount,
            token_amount=token_amount,
            probability=probability,
            rarity_label=rarity_label,
            is_active=is_active,
            sort_order=sort_order,
        )
        flash("Предмет добавлен в кейс", "success")
    except Exception as e:
        delete_local_upload(image_url)
        flash(f"Ошибка добавления предмета: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/<int:case_id>/items/<int:item_id>/update', methods=['POST'])
@owner_required
def case_item_update(case_id, item_id):
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    item = get_case_item_by_id(item_id, club_id)
    if not item or int(item.get("case_id")) != int(case_id):
        flash("Предмет не найден", "error")
        return _redirect_wheel()

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    bonus_raw = request.form.get("bonus_amount", "").strip()
    token_raw = request.form.get("token_amount", "").strip()
    probability_raw = request.form.get("probability", "").strip()
    rarity_label = _parse_rarity_label(request.form.get("rarity_label", "Обычный"))
    is_active = 1 if request.form.get("is_active") == "1" else 0

    if not name:
        flash("Укажи название предмета", "error")
        return _redirect_wheel()

    old_image_url = item.get("image_url")

    try:
        probability = _parse_probability(probability_raw)
        bonus_amount = _parse_int(bonus_raw, "Количество КБ")
        token_amount = _parse_int(token_raw, "Количество жетонов")
        image_url = _get_uploaded_image_url(
            club_id=club_id,
            kind="case_item",
            existing_url=old_image_url,
        )
    except (ValueError, UploadError) as e:
        flash(str(e), "error")
        return _redirect_wheel()

    try:
        update_case_item(
            item_id=item_id,
            club_id=club_id,
            case_id=case_id,
            name=name,
            description=description or None,
            image_url=image_url,
            bonus_amount=bonus_amount,
            token_amount=token_amount,
            probability=probability,
            rarity_label=rarity_label,
            is_active=is_active,
            sort_order=int(item.get("sort_order") or 0),
        )
        _delete_old_image_if_replaced(old_image_url, image_url)
        flash("Предмет обновлён", "success")
    except Exception as e:
        if image_url != old_image_url:
            delete_local_upload(image_url)
        flash(f"Ошибка обновления предмета: {e}", "error")

    return _redirect_wheel()


@owner_bp.route('/cases/<int:case_id>/items/<int:item_id>/delete', methods=['POST'])
@owner_required
def case_item_delete(case_id, item_id):
    club_id = _require_club_id()
    if club_id is None:
        return redirect(url_for("owner.club_create"))

    item = get_case_item_by_id(item_id, club_id)
    image_url = item.get("image_url") if item else None

    try:
        delete_case_item(item_id, club_id)
        delete_local_upload(image_url)
        flash("Предмет удалён", "success")
    except Exception as e:
        flash(f"Ошибка удаления предмета: {e}", "error")

    return _redirect_wheel()
