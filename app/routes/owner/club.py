from flask import flash, redirect, render_template, request, session, url_for

from app.core import get_db_connection, owner_required

from . import owner_bp


@owner_bp.route("/club/create", methods=["GET", "POST"])
@owner_required
def club_create():
    if request.method == "POST":
        club_id = request.form.get("club_id", "").strip()
        name = request.form.get("name", "").strip()
        lg_api_key = request.form.get("lg_api_key", "").strip()
        secret = request.form.get("secret", "").strip()

        if not club_id or not name or not lg_api_key or not secret:
            flash("Заполни все поля клуба", "error")
            return redirect(url_for("owner.club_create"))

        try:
            club_id = int(club_id)
        except ValueError:
            flash("club_id должен быть числом", "error")
            return redirect(url_for("owner.club_create"))

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT club_id FROM clubs WHERE club_id = %s LIMIT 1", (club_id,))
                if cursor.fetchone():
                    flash("Клуб с таким club_id уже существует", "error")
                    return redirect(url_for("owner.club_create"))

                cursor.execute(
                    """
                    INSERT INTO clubs (club_id, owner_id, name, lg_api_key, secret)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (club_id, session["user_id"], name, lg_api_key, secret),
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET club_id = %s
                    WHERE user_id = %s
                    """,
                    (club_id, session["user_id"]),
                )

            conn.commit()
            session["club_id"] = club_id
            flash("Клуб успешно создан", "success")
            return redirect(url_for("owner.dashboard"))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f"Ошибка при создании клуба: {e}", "error")
            return redirect(url_for("owner.club_create"))
        finally:
            if conn:
                conn.close()

    return render_template("owner/club_create.html")
