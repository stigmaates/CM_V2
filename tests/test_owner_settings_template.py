from types import SimpleNamespace

from flask import render_template

from app.main import app


def test_owner_settings_renders_guest_login_copy_link():
    with app.test_request_context("/owner/settings"):
        html = render_template(
            "owner/settings.html",
            active_tab="club",
            club=SimpleNamespace(
                name="WALLZ",
                lg_api_key="key",
                secret="secret",
                cm_bonus_admin_chat_id="",
                instagram_url="",
                youtube_url="",
                vk_url="",
                telegram_channel_url="",
                yandex_maps_url="",
                two_gis_url="",
            ),
            guest_login_url="https://cyber-bonus.ru/guest/login?club_id=1",
            pc_name_settings=[],
            system_status={"updates": [], "auto_mailings": []},
        )

    assert "Ссылка входа гостей" in html
    assert "https://cyber-bonus.ru/guest/login?club_id=1" in html
    assert "copyGuestLoginUrlBtn" in html
    assert "Открыть как гость" in html
    assert "/owner/settings/guest-test" in html


def test_owner_settings_renders_profile_tab_and_linked_club():
    with app.test_request_context("/owner/settings?tab=profile"):
        from flask import session

        session["role"] = "owner"
        html = render_template(
            "owner/settings.html",
            active_tab="profile",
            profile_user=SimpleNamespace(
                user_id=7,
                name="Дмитрий",
                login="owner@example.com",
                role="owner",
                club_id=2,
                club_name="VENOM",
            ),
        )

    assert "Профиль" in html
    assert "Сохранить профиль" in html
    assert "owner@example.com" in html
    assert "VENOM" in html
    assert "Владелец" in html
    assert "/owner/settings/profile" in html


def test_owner_settings_renders_guest_management_and_histories():
    with app.test_request_context("/owner/settings?tab=guests&phone=79990000000"):
        from flask import session

        session["role"] = "owner"
        html = render_template(
            "owner/settings.html",
            active_tab="guests",
            guest_management_phone="79990000000",
            guest_lookup={
                "found": True,
                "guest": {
                    "guest_id": 22,
                    "fio": "Иван Петров",
                    "phone": "79990000000",
                    "has_telegram": True,
                    "bonus_balance": 500,
                    "token_balance": 4,
                    "is_banned": False,
                    "reason": None,
                },
                "bonus_transactions": [],
                "token_transactions": [],
            },
        )

    assert "Управление гостями" in html
    assert "Иван Петров" in html
    assert "500 КБ" in html
    assert "/owner/settings/guests/adjust" in html
    assert "/owner/settings/guests/access" in html
    assert "Заблокировать" in html


def test_admin_owner_impersonation_shows_guest_management_without_profile():
    with app.test_request_context("/owner/settings"):
        from flask import session

        session["role"] = "admin"
        session["impersonating_owner"] = True
        html = render_template(
            "owner/settings.html",
            active_tab="club",
            club=SimpleNamespace(
                name="VENOM",
                lg_api_key="key",
                secret="secret",
                cm_bonus_admin_chat_id="",
                instagram_url="",
                youtube_url="",
                vk_url="",
                telegram_channel_url="",
                yandex_maps_url="",
                two_gis_url="",
            ),
            guest_login_url="https://cyber-bonus.ru/guest/login?club_id=2",
            pc_name_settings=[],
            system_status={"updates": [], "auto_mailings": []},
        )

    assert "Управление гостями" in html
    assert 'tab=profile' not in html
