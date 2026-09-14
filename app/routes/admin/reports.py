from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

from app.core import admin_required, get_db_connection
from app.routes.admin import admin_bp
from app.services.monthly_report_view import build_monthly_report_view
from app.services.monthly_reports import REPORT_VERSION, month_bounds, previous_month

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _clubs(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT club_id,name,timezone FROM clubs ORDER BY name,club_id")
        return list(cursor.fetchall())


def _saved_reports(conn):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT mr.id,mr.club_id,mr.report_year,mr.report_month,mr.status,mr.generated_at,
                   mr.version,mr.error_message,c.name AS club_name
            FROM monthly_reports mr
            JOIN clubs c ON c.club_id=mr.club_id
            ORDER BY mr.generated_at DESC,mr.id DESC
            LIMIT 100
            """)
        return list(cursor.fetchall())


def _load_report(conn, report_id):
    if not report_id:
        return None
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM monthly_reports WHERE id=%s LIMIT 1", (report_id,))
        row = cursor.fetchone()
    if not row or row["status"] != "ready":
        return None
    row["data"] = json.loads(row["report_data_json"])
    row["view"] = build_monthly_report_view(row["data"])
    return row


@admin_bp.route("/reports")
@admin_required
def reports():
    conn = get_db_connection()
    try:
        clubs = _clubs(conn)
        saved = _saved_reports(conn)
        selected = _load_report(conn, request.args.get("report_id", type=int))
    finally:
        conn.close()
    now = datetime.now()
    default_year, default_month = previous_month(now.year, now.month)
    return render_template(
        "admin/reports.html",
        active_page="reports",
        clubs=clubs,
        reports=saved,
        has_pending_reports=any(row["status"] in {"queued", "running"} for row in saved),
        selected=selected,
        default_year=default_year,
        default_month=default_month,
        current_year=now.year,
        month_options=[
            (1, "Январь"),
            (2, "Февраль"),
            (3, "Март"),
            (4, "Апрель"),
            (5, "Май"),
            (6, "Июнь"),
            (7, "Июль"),
            (8, "Август"),
            (9, "Сентябрь"),
            (10, "Октябрь"),
            (11, "Ноябрь"),
            (12, "Декабрь"),
        ],
    )


@admin_bp.route("/reports/generate", methods=["POST"])
@admin_required
def generate_report():
    club_id = request.form.get("club_id", type=int)
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)
    if not club_id or year is None or month is None:
        flash("Выберите клуб, месяц и год", "error")
        return redirect(url_for("admin.reports"))

    try:
        month_bounds(year, month)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.reports"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO monthly_reports
                    (club_id,report_year,report_month,status,generated_at,generated_by,
                     report_data_json,pdf_path,version,error_message)
                VALUES (%s,%s,%s,'queued',UTC_TIMESTAMP(),%s,'{}','',%s,NULL)
                ON DUPLICATE KEY UPDATE status='queued',generated_at=UTC_TIMESTAMP(),
                    generated_by=VALUES(generated_by),error_message=NULL
                """,
                (club_id, year, month, session.get("user_id"), REPORT_VERSION),
            )
            cursor.execute(
                "SELECT id FROM monthly_reports WHERE club_id=%s AND report_year=%s AND report_month=%s AND version=%s",
                (club_id, year, month, REPORT_VERSION),
            )
            report_id = cursor.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "generate_monthly_report.py"),
                "--report-id",
                str(report_id),
            ],
            cwd=PROJECT_ROOT,
            start_new_session=True,
        )
    except OSError as exc:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE monthly_reports SET status='failed',error_message=%s WHERE id=%s",
                    (f"Не удалось запустить сборку: {exc}"[:2000], report_id),
                )
            conn.commit()
        finally:
            conn.close()
        flash("Не удалось запустить формирование отчёта", "error")
        return redirect(url_for("admin.reports"))

    flash("Отчёт поставлен в очередь. Страница обновится автоматически.", "success")
    return redirect(url_for("admin.reports"))


@admin_bp.route("/reports/<int:report_id>/download")
@admin_required
def download_report(report_id):
    conn = get_db_connection()
    try:
        report = _load_report(conn, report_id)
    finally:
        conn.close()
    if not report:
        abort(404)
    path = Path(report["pdf_path"])
    if not path.is_file():
        abort(404, description="PDF-файл отчёта не найден")
    club_name = report["data"]["club"]["name"].replace("/", "-")
    return send_file(
        path,
        as_attachment=True,
        download_name=f"Cyber Bonus — {club_name} — {report['report_year']}-{report['report_month']:02d}.pdf",
        mimetype="application/pdf",
    )
