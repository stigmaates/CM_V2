from app.main import app
from app.services.reception import _phone_variants, _source_label


def test_reception_role_is_redirected_back_to_reception_from_owner_page():
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 11
        session["role"] = "reception"
        session["club_id"] = 1

    response = client.get("/owner/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/reception/")


def test_reception_phone_variants_cover_common_russian_formats():
    variants = _phone_variants("+7 (987) 153-68-67")

    assert "79871536867" in variants
    assert "89871536867" in variants
    assert "9871536867" in variants


def test_reception_phone_variants_match_local_number_from_leading_eight():
    variants = _phone_variants("89270086145")

    assert "89270086145" in variants
    assert "79270086145" in variants
    assert "9270086145" in variants


def test_reception_labels_topup_reward_in_russian():
    assert _source_label("topup_reward") == "Бонус за пополнение"
