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
