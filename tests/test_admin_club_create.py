from app.routes.admin.clubs import _insert_admin_club, _next_club_id


class FakeCursor:
    def __init__(self, existing_club=False, service_enabled_column=True, next_club_id=12):
        self.existing_club = existing_club
        self.service_enabled_column = service_enabled_column
        self.next_club_id = next_club_id
        self.queries = []
        self._next_result = None

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if "MAX(club_id)" in sql:
            self._next_result = {"club_id": self.next_club_id}
            return
        if "FROM clubs WHERE club_id" in sql:
            self._next_result = {"club_id": params[0]} if self.existing_club else None
            return
        if "information_schema.COLUMNS" in sql:
            self._next_result = {"cnt": 1 if self.service_enabled_column else 0}
            return
        self._next_result = None

    def fetchone(self):
        return self._next_result


def test_next_club_id_uses_next_available_number():
    cursor = FakeCursor(next_club_id=8)

    assert _next_club_id(cursor) == 8


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


def test_gizmo_club_is_disabled_without_langame_credentials_on_stage(monkeypatch):
    from app.routes.admin import clubs
    monkeypatch.setattr(clubs, 'APP_ENV', 'stage')
    cursor = FakeCursor()
    clubs._insert_admin_club(cursor, 900001, 'Next, Уфа', '', '', provider='gizmo', timezone_name='Asia/Yekaterinburg')
    insert_sql, params = cursor.queries[-2]
    assert "NULL,0,'gizmo',0" in insert_sql
    assert params == (900001, 'Next, Уфа', 'Asia/Yekaterinburg')
    assert 'club_integrations' in cursor.queries[-1][0]


def test_gizmo_creation_is_not_enabled_in_production(monkeypatch):
    import pytest

    from app.routes.admin import clubs
    monkeypatch.setattr(clubs, 'APP_ENV', 'production')
    cursor = FakeCursor()
    with pytest.raises(ValueError, match='стейдже'):
        clubs._insert_admin_club(cursor, 900001, 'Next', '', '', provider='gizmo')
    assert not any('INSERT INTO' in sql for sql, _ in cursor.queries)
