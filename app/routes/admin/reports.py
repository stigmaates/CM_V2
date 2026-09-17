from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

from app.config import MONTHLY_REPORT_ROOT
from app.core import admin_required, get_db_connection
from app.routes.admin import admin_bp
from app.services.monthly_report_view import build_monthly_report_view
from app.services.monthly_reports import REPORT_VERSION, calculate_monthly_report, json_dumps, previous_month


def _clubs(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT club_id,name,timezone FROM clubs ORDER BY name,club_id")
        return list(cursor.fetchall())


def _saved_reports(conn):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT mr.id,mr.club_id,mr.report_year,mr.report_month,mr.status,mr.generated_at,mr.version,c.name AS club_name
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
    if not row:
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
    from app.services.monthly_report_pdf import render_monthly_report_pdf

    club_id = request.form.get("club_id", type=int)
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)
    if not club_id or year is None or month is None:
        flash("Выберите клуб, месяц и год", "error")
        return redirect(url_for("admin.reports"))

    conn = get_db_connection()
    try:
        data = calculate_monthly_report(conn, club_id, year, month)
        view = build_monthly_report_view(data)
        report_dir = Path(MONTHLY_REPORT_ROOT) / str(club_id) / str(year)
        report_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = report_dir / f"{month:02d}-{REPORT_VERSION}.pdf"
        temporary_path = report_dir / f".{month:02d}-{REPORT_VERSION}.tmp.pdf"
        render_monthly_report_pdf(view, temporary_path)
        os.replace(temporary_path, pdf_path)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO monthly_reports
                    (club_id,report_year,report_month,status,generated_at,generated_by,report_data_json,pdf_path,version)
                VALUES (%s,%s,%s,'ready',UTC_TIMESTAMP(),%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE status=VALUES(status),generated_at=VALUES(generated_at),
                    generated_by=VALUES(generated_by),report_data_json=VALUES(report_data_json),pdf_path=VALUES(pdf_path)
                """,
                (club_id, year, month, session.get("user_id"), json_dumps(data), str(pdf_path), REPORT_VERSION),
            )
            cursor.execute(
                "SELECT id FROM monthly_reports WHERE club_id=%s AND report_year=%s AND report_month=%s AND version=%s",
                (club_id, year, month, REPORT_VERSION),
            )
            report_id = cursor.fetchone()["id"]
        conn.commit()
    except (ValueError, OSError) as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin.reports"))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    flash("Отчёт сформирован и сохранён", "success")
    return redirect(url_for("admin.reports", report_id=report_id))


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
