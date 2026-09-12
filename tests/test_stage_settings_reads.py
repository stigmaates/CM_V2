from app.services import pc_heatmap, stage_mirror, system_status


class ReadOnlyConnection:
    def __init__(self):
        self.sql = []
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, args=()):
        assert sql.strip().startswith('SELECT'), 'Page read attempted a write or DDL'
        self.sql.append((sql, args))

    def fetchall(self):
        if 'club_pc_names' in self.sql[-1][0]:
            return [dict(uuid='pc-1', display_name='VIP 1', sort_order=10, total_hours=3, sessions_count=2)]
        return []

    def fetchone(self):
        return {'timezone': 'Europe/Moscow'}

    def commit(self):
        pass

    def close(self):
        self.closed = True


def test_mirror_marker_is_local_not_message_environment(monkeypatch, tmp_path):
    marker = tmp_path / '.stage-no-outbound'
    monkeypatch.setattr(stage_mirror, 'MIRROR_MARKER', marker)
    monkeypatch.setenv('DISABLE_OUTBOUND_MESSAGES', '1')
    assert not stage_mirror.stage_mirror_enabled()
    marker.touch()
    assert stage_mirror.stage_mirror_enabled()


def test_stage_pc_settings_and_heatmap_read_without_write_locks(monkeypatch):
    for read in (pc_heatmap.get_pc_name_settings, pc_heatmap.get_pc_hours_heatmap_stats):
        conn = ReadOnlyConnection()
        monkeypatch.setattr(pc_heatmap, 'get_db_connection', lambda: conn)
        monkeypatch.setattr(pc_heatmap, 'stage_mirror_enabled', lambda: True)
        result = read(7)
        assert conn.closed and len(conn.sql) == 1
        assert conn.sql[0][1][-1] == 7
        if isinstance(result, list):
            assert result[0]['effective_name'] == 'VIP 1'
        else:
            assert result['pcs'][0]['name'] == 'VIP 1'
            assert result['total_hours'] == 3


def test_non_mirror_keeps_existing_pc_discovery(monkeypatch):
    calls = []
    conn = ReadOnlyConnection()
    monkeypatch.setattr(pc_heatmap, 'get_db_connection', lambda: conn)
    monkeypatch.setattr(pc_heatmap, 'stage_mirror_enabled', lambda: False)
    monkeypatch.setattr(pc_heatmap, 'ensure_pc_names_table', lambda cur: calls.append('ensure'))
    monkeypatch.setattr(pc_heatmap, '_sync_recent_session_uuids', lambda cur, cid: calls.append(cid))
    pc_heatmap.get_pc_name_settings(7)
    assert calls == ['ensure', 7]


def test_stage_system_status_does_not_initialize_mailings(monkeypatch):
    conn = ReadOnlyConnection()
    monkeypatch.setattr(system_status, 'get_db_connection', lambda: conn)
    monkeypatch.setattr(system_status, 'stage_mirror_enabled', lambda: True)
    monkeypatch.setattr(system_status, 'get_latest_job_runs_by_club', lambda types: {})
    def forbidden(*args):
        raise AssertionError('Viewing status must not initialize mailing settings')
    monkeypatch.setattr(system_status, 'ensure_auto_mailings', forbidden)
    system_status.get_owner_settings_system_status(7)
    assert conn.closed and len(conn.sql) == 2
