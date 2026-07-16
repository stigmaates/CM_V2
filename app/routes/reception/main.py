from flask import redirect, render_template, request, session, url_for

from app.core import reception_required
from app.services.reception import get_reception_guest_lookup

from . import reception_bp


@reception_bp.route("/")
@reception_required
def dashboard():
    club_id = session.get("club_id")
    phone = request.args.get("phone", "").strip()
    lookup = None
    setup_error = None

    if not club_id:
        setup_error = "Для пользователя reception не указан club_id. Создайте пользователя с привязкой к клубу."
    elif phone:
        lookup = get_reception_guest_lookup(club_id=int(club_id), phone=phone)

    return render_template(
        "reception/dashboard.html",
        phone=phone,
        lookup=lookup,
        setup_error=setup_error,
    )


@reception_bp.route("/logout")
@reception_required
def logout():
    return redirect(url_for("auth.logout"))
