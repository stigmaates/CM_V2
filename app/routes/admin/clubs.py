from flask import redirect, render_template, request

from app.core import get_db_connection
from app.routes.admin import admin_bp
from app.routes.common.auth import admin_required


@admin_bp.route("/clubs/create", methods=["GET", "POST"])
@admin_required
def create_club():
    if request.method == "POST":
        name = request.form.get("name")
        api_key = request.form.get("api_key")
        secret = request.form.get("secret")

        if not name or not api_key or not secret:
            return "Заполни все поля", 400

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO clubs (name, lg_api_key, secret, owner_id)
                VALUES (%s, %s, %s, NULL)
                """,
                (name, api_key, secret),
            )
            db.commit()

        return redirect("/admin/clubs")

    return render_template("admin/create_club.html")
