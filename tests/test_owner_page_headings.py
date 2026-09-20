from pathlib import Path


OWNER_TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates" / "owner"


def test_every_owner_workspace_page_uses_shared_heading_component():
    pages = (
        "crm_analytics.html",
        "dashboard.html",
        "guest_pulse.html",
        "mailing.html",
        "missions.html",
        "prize_claims.html",
        "promotions.html",
        "settings.html",
        "team.html",
        "training.html",
        "wheel_settings.html",
    )

    for page in pages:
        source = (OWNER_TEMPLATES / page).read_text(encoding="utf-8")
        assert "owner-page-heading" in source, page
        assert "owner-page-heading__title" in source, page
        assert "owner-page-heading__subtitle" in source, page


def test_shared_heading_matches_cohort_typography():
    css = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "css"
        / "theme.css"
    ).read_text(encoding="utf-8")

    assert "font-size: clamp(32px, 3vw, 46px);" in css
    assert "font-weight: 900;" in css
    assert "letter-spacing: -.035em;" in css
    assert ".owner-page .owner-page-heading__subtitle" in css
