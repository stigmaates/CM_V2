from app.routes.admin.users import _validate_club_for_user_create


class FakeCursor:
    def __init__(self, club=None):
        self.club = club
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self.club


def test_validate_club_for_user_create_ignores_admin_without_club():
    assert _validate_club_for_user_create(FakeCursor(), "admin", None) is None


def test_validate_club_for_user_create_requires_club_for_owner_and_reception():
    assert "нужно указать" in _validate_club_for_user_create(FakeCursor(), "owner", None)
    assert "нужно указать" in _validate_club_for_user_create(FakeCursor(), "reception", None)


def test_validate_club_for_user_create_rejects_missing_club():
    assert "не найден" in _validate_club_for_user_create(FakeCursor(club=None), "owner", 7)


def test_validate_club_for_user_create_rejects_second_owner():
    cursor = FakeCursor(club={"club_id": 7, "owner_id": 15})

    assert "уже есть владелец" in _validate_club_for_user_create(cursor, "owner", 7)


def test_validate_club_for_user_create_allows_owner_for_free_club():
    cursor = FakeCursor(club={"club_id": 7, "owner_id": None})

    assert _validate_club_for_user_create(cursor, "owner", 7) is None
