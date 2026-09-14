from app.services import monthly_report_generation as generation


class FakeCursor:
    def __init__(self):
        self.rowcount = 0
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "status='running'" in sql:
            self.rowcount = 1

    def fetchone(self):
        return {"club_id": 4, "report_year": 2026, "report_month": 8}


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_background_report_claims_renders_and_finishes(monkeypatch, tmp_path):
    conn = FakeConnection()
    monkeypatch.setattr(generation, "get_db_connection", lambda: conn)
    monkeypatch.setattr(generation, "MONTHLY_REPORT_ROOT", str(tmp_path))
    monkeypatch.setattr(generation, "calculate_monthly_report", lambda *_args: {"calculated": True})
    monkeypatch.setattr(generation, "build_monthly_report_view", lambda data: {"view": data})

    def fake_render(_view, path):
        path.write_bytes(b"pdf")

    monkeypatch.setattr(generation, "_render_report", fake_render)

    assert generation.generate_saved_monthly_report(9) is True
    assert (tmp_path / "4" / "2026" / "08-v1.pdf").read_bytes() == b"pdf"
    assert any("status='ready'" in sql for sql, _params in conn.fake_cursor.executed)
    assert conn.commits == 2
    assert conn.closed is True
