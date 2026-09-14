"""Background generation of saved monthly reports."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import MONTHLY_REPORT_ROOT
from app.core import get_db_connection
from app.services.monthly_report_view import build_monthly_report_view
from app.services.monthly_reports import REPORT_VERSION, calculate_monthly_report, json_dumps

logger = logging.getLogger(__name__)


def _render_report(view, output_path: Path) -> None:
    from app.services.monthly_report_pdf import render_monthly_report_pdf

    render_monthly_report_pdf(view, output_path)


def _mark_failed(report_id: int, error: Exception) -> None:
    message = f"{type(error).__name__}: {error}"[:2000]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE monthly_reports SET status='failed',error_message=%s WHERE id=%s",
                (message, report_id),
            )
        conn.commit()
    finally:
        conn.close()


def generate_saved_monthly_report(report_id: int) -> bool:
    """Claim and generate one queued report. Returns False if it was not queued."""
    conn = get_db_connection()
    temporary_path: Path | None = None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE monthly_reports SET status='running',error_message=NULL " "WHERE id=%s AND status='queued'",
                (report_id,),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False
            cursor.execute(
                "SELECT club_id,report_year,report_month FROM monthly_reports WHERE id=%s LIMIT 1",
                (report_id,),
            )
            report = cursor.fetchone()
        conn.commit()
        if not report:
            return False

        club_id = int(report["club_id"])
        year = int(report["report_year"])
        month = int(report["report_month"])
        data = calculate_monthly_report(conn, club_id, year, month)
        view = build_monthly_report_view(data)

        report_dir = Path(MONTHLY_REPORT_ROOT) / str(club_id) / str(year)
        report_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = report_dir / f"{month:02d}-{REPORT_VERSION}.pdf"
        temporary_path = report_dir / f".{month:02d}-{REPORT_VERSION}-{report_id}.tmp.pdf"
        _render_report(view, temporary_path)
        os.replace(temporary_path, pdf_path)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE monthly_reports
                SET status='ready',generated_at=UTC_TIMESTAMP(),report_data_json=%s,
                    pdf_path=%s,error_message=NULL
                WHERE id=%s
                """,
                (json_dumps(data), str(pdf_path), report_id),
            )
        conn.commit()
        return True
    except Exception as error:
        logger.exception("Monthly report %s generation failed", report_id)
        try:
            conn.rollback()
        except Exception:
            pass
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        try:
            _mark_failed(report_id, error)
        except Exception:
            logger.exception("Could not mark monthly report %s as failed", report_id)
        return False
    finally:
        conn.close()
