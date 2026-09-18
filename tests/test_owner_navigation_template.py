from flask import render_template, session

from app.main import app


def test_owner_navigation_groups_existing_owner_pages():
    with app.test_request_context("/owner/settings?tab=contracts"):
        session["role"] = "owner"
        html = render_template(
            "owner/_navigation.html",
            header_club_name="Тестовый клуб",
            header_user_name="Владелец",
        )

    for group in ("Геймификация", "CRM", "Аналитика", "Управление", "Обучение"):
        assert group in html

    for item in (
        "Настройки кейсов и колеса фортуны",
        "Задания",
        "Контракты",
        "Акции",
        "Управляемое выпадение",
        "Рассылки и авторассылки",
        "Пульс гостя",
        "Анализ по когортам",
        "Анализ коммуникаций",
        "Тепловые карты",
        "Команда",
        "Настройки",
        "Управление гостями",
    ):
        assert item in html

    assert 'id="ownerNavigation"' in html
    assert "owner-navigation__close" not in html
    assert "/owner/analytics/cohorts" in html
    assert "/owner/analytics/communications" in html
    assert "/owner/analytics/heatmaps" in html
    assert "/owner/promotions" in html
    assert "#prize-editor" in html


def test_owner_base_uses_burger_navigation_assets():
    with app.test_request_context("/owner/dashboard"):
        html = render_template(
            "owner/base.html",
            header_club_name="Тестовый клуб",
            header_user_name="Владелец",
        )

    assert "data-owner-menu-open" in html
    assert html.count("data-owner-menu-open") == 1
    assert "owner-menu-trigger__arrow" in html
    assert 'id="ownerNavigation"' in html
    assert "owner_navigation.js" in html
    assert 'class="owner-topnav"' not in html
