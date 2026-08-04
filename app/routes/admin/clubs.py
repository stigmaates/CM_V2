from flask import flash, redirect, render_template, request, url_for

from app.core import get_db_connection
from app.routes.admin import admin_bp
from app.routes.common.auth import admin_required


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    row = cursor.fetchone()
    return bool(row and row.get("cnt"))


def _next_club_id(cursor) -> int:
    cursor.execute("SELECT COALESCE(MAX(club_id), 0) + 1 AS club_id FROM clubs")
    row = cursor.fetchone() or {}
    return int(row.get("club_id") or 1)


def _insert_admin_club(cursor, club_id: int, name: str, api_key: str, secret: str) -> None:
    cursor.execute("SELECT club_id FROM clubs WHERE club_id = %s LIMIT 1", (club_id,))
    if cursor.fetchone():
        raise ValueError("Клуб с таким club_id уже существует")

    if _column_exists(cursor, "clubs", "service_enabled"):
        cursor.execute(
            """
            INSERT INTO clubs (club_id, name, lg_api_key, secret, owner_id, service_enabled)
            VALUES (%s, %s, %s, %s, NULL, 0)
            """,
            (club_id, name, api_key, secret),
        )
        return

    cursor.execute(
        """
        INSERT INTO clubs (club_id, name, lg_api_key, secret, owner_id)
        VALUES (%s, %s, %s, %s, NULL)
        """,
        (club_id, name, api_key, secret),
    )


@admin_bp.route("/clubs/create", methods=["GET", "POST"])
@admin_required
def create_club():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        api_key = (request.form.get("api_key") or "").strip()
        secret = (request.form.get("secret") or "").strip()

        if not name or not api_key or not secret:
            flash("Заполни название, API key и secret", "error")
            return redirect(url_for("admin.create_club"))

        with get_db_connection() as db:
            cur = db.cursor()
            try:
                club_id = _next_club_id(cur)
                _insert_admin_club(cur, club_id, name, api_key, secret)
                db.commit()
            except ValueError as exc:
                db.rollback()
                flash(str(exc), "error")
                return redirect(url_for("admin.create_club"))

        flash(f"Клуб создан выключенным. Внутренний ID: {club_id}. Включи обслуживание после проверки API.", "success")
        return redirect("/admin/clubs")

    return render_template("admin/create_club.html")
