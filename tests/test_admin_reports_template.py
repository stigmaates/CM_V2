from datetime import datetime

from flask import render_template

from app.main import app


def test_reports_page_shows_background_generation_status():
    with app.test_request_context("/admin/reports"):
        html = render_template(
            "admin/reports.html",
            active_page="reports",
            clubs=[],
            reports=[
                {
                    "id": 7,
                    "club_id": 1,
                    "club_name": "Тестовый клуб",
                    "report_year": 2026,
                    "report_month": 8,
                    "generated_at": datetime(2026, 9, 14, 20, 0),
                    "version": "v1",
                    "status": "running",
                    "error_message": None,
                }
            ],
            selected=None,
            has_pending_reports=True,
            default_year=2026,
            default_month=8,
            current_year=2026,
            month_options=[(8, "Август")],
        )

    assert "Формируется" in html
    assert "Можно закрыть страницу" in html
    assert "window.location.reload()" in html
    assert "/admin/reports/7/download" not in html
