from contextlib import nullcontext

from flask import flash, redirect, render_template, request, url_for

from app.core import get_db_connection
from app.integrations.gizmo_onboarding import initial_setup, prepare_connection, public_error
from app.integrations.gizmo_runtime import gizmo_available
from app.integrations.providers import validate_provider
from app.routes.admin import admin_bp
from app.routes.common.auth import admin_required
from app.services.timezones import CLUB_TIMEZONE_CHOICES, validate_club_timezone


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


def _insert_admin_club(
    cursor, club_id: int, name: str, api_key: str, secret: str, *, provider="langame", timezone_name=None
) -> None:
    provider = validate_provider(provider)
    cursor.execute("SELECT club_id FROM clubs WHERE club_id = %s LIMIT 1", (club_id,))
    if cursor.fetchone():
        raise ValueError("Клуб с таким club_id уже существует")

    if provider == "gizmo":
        if not gizmo_available():
            raise ValueError("Подключение Gizmo не включено в этом окружении")
        if not _column_exists(cursor, "clubs", "integration_provider"):
            raise ValueError("Сначала примените миграцию интеграций")
        cursor.execute(
            """INSERT INTO clubs
            (club_id, name, timezone, lg_api_key, secret, owner_id, service_enabled,
             integration_provider, integration_ready)
            VALUES (%s,%s,%s,'','',NULL,0,'gizmo',0)""",
            (club_id, name, validate_club_timezone(timezone_name)),
        )
        cursor.execute("INSERT INTO club_integrations (club_id) VALUES (%s)", (club_id,))
        return

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


def _creation_form():
    # Never send secrets back to the browser after validation errors.
    values = {
        key: request.form.get(key, "")
        for key in ("name", "integration_provider", "timezone", "address", "port", "server_name")
    }
    return render_template(
        "admin/create_club.html",
        gizmo_enabled=gizmo_available(),
        timezone_choices=CLUB_TIMEZONE_CHOICES,
        values=values,
    )


@admin_bp.route("/clubs/create", methods=["GET", "POST"])
@admin_required
def create_club():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        api_key = (request.form.get("api_key") or "").strip()
        secret = (request.form.get("secret") or "").strip()
        credentials = None
        try:
            provider = validate_provider(request.form.get("integration_provider"))
            timezone_name = validate_club_timezone(request.form.get("timezone"))
            if not name:
                raise ValueError("Укажите название клуба.")
            if provider == "langame" and (not api_key or not secret):
                raise ValueError("Заполните API key и secret Langame.")
            if provider == "gizmo":
                if not gizmo_available():
                    raise ValueError("Подключение Gizmo не включено в этом окружении.")
                credentials = prepare_connection(
                    {**request.form, "api_key": request.form.get("gizmo_api_key", "")},
                )
        except (ValueError, OSError) as exc:
            flash(str(exc) if isinstance(exc, ValueError) else public_error(exc), "error")
            return _creation_form(), 400

        with get_db_connection() as db:
            cur = db.cursor()
            try:
                club_id = _next_club_id(cur)
                # The scheduler cannot observe this club until SQL commits and
                # the per-club lock is released. Failed creation removes only
                # its newly written credentials, never another club's files.
                setup = initial_setup(club_id, credentials) if provider == "gizmo" else nullcontext()
                with setup:
                    _insert_admin_club(
                        cur,
                        club_id,
                        name,
                        api_key if provider == "langame" else "",
                        secret if provider == "langame" else "",
                        provider=provider,
                        timezone_name=timezone_name,
                    )
                    if provider == "langame":
                        cur.execute("UPDATE clubs SET timezone=%s WHERE club_id=%s", (timezone_name, club_id))
                    db.commit()
            except (ValueError, OSError) as exc:
                db.rollback()
                flash(
                    (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "Не удалось сохранить подключение Gizmo. Повторите создание."
                    ),
                    "error",
                )
                return _creation_form(), 400
            except Exception:
                db.rollback()
                flash("Не удалось создать клуб. Повторите попытку.", "error")
                return _creation_form(), 500

        if provider == "gizmo":
            flash(
                f"Клуб создан. Внутренний ID: {club_id}. Проверка и загрузка данных запустятся автоматически.",
                "success",
            )
            return redirect(url_for("admin.gizmo_setup", club_id=club_id))
        flash(f"Клуб создан выключенным. Внутренний ID: {club_id}. Включи обслуживание после проверки API.", "success")
        return redirect("/admin/clubs")

    return _creation_form()
