from app.routes.admin.clubs import _insert_admin_club, _parse_club_id


class FakeCursor:
    def __init__(self, existing_club=False, service_enabled_column=True):
        self.existing_club = existing_club
        self.service_enabled_column = service_enabled_column
        self.queries = []
        self._next_result = None

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if "FROM clubs WHERE club_id" in sql:
            self._next_result = {"club_id": params[0]} if self.existing_club else None
            return
        if "information_schema.COLUMNS" in sql:
            self._next_result = {"cnt": 1 if self.service_enabled_column else 0}
            return
        self._next_result = None

    def fetchone(self):
        return self._next_result


def test_parse_club_id_accepts_positive_numbers():
    assert _parse_club_id("12") == 12


def test_parse_club_id_rejects_empty_non_numeric_and_zero():
    assert _parse_club_id("") is None
    assert _parse_club_id("abc") is None
    assert _parse_club_id("0") is None


def test_insert_admin_club_creates_disabled_club_when_column_exists():
    cursor = FakeCursor(service_enabled_column=True)

    _insert_admin_club(cursor, 12, "New Club", "api", "secret")

    insert_sql, insert_params = cursor.queries[-1]
    assert "service_enabled" in insert_sql
    assert insert_params == (12, "New Club", "api", "secret")
    assert "NULL, 0" in insert_sql


def test_insert_admin_club_raises_for_duplicate_club_id():
    cursor = FakeCursor(existing_club=True)

    try:
        _insert_admin_club(cursor, 12, "New Club", "api", "secret")
    except ValueError as exc:
        assert "уже существует" in str(exc)
    else:
        raise AssertionError("expected duplicate club_id to fail")
