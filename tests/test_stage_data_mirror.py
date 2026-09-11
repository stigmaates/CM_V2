import sqlite3

import pytest

from scripts import mirror_production_to_stage as mirror
from scripts import setup_stage_mirror as setup


@pytest.fixture(autouse=True)
def source_test_keys(monkeypatch):
    monkeypatch.setattr(mirror, 'primary_key', lambda conn, table: ['id'])


class Cursor:
    def __init__(self, connection, kind=None):
        self.connection = connection
        self.cursor = connection.db.cursor()
        self.dict_rows = kind is mirror.DictCursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, args=()):
        self.connection.statements.append(sql)
        if sql.startswith(('SET ', 'START TRANSACTION')):
            return
        if self.connection.fail and sql.startswith('INSERT INTO `guests`'):
            raise RuntimeError('injected insert failure')
        self.cursor.execute(sql.replace('%s', '?'), args)

    def executemany(self, sql, batch):
        for row in batch:
            self.execute(sql, row)

    def fetchmany(self, size):
        return self.cursor.fetchmany(size)

    def fetchall(self):
        values = self.cursor.fetchall()
        if self.dict_rows:
            names = [column[0] for column in self.cursor.description]
            return [dict(zip(names, row)) for row in values]
        return values


class Connection:
    def __init__(self, value, fail=False):
        self.db = sqlite3.connect(':memory:')
        self.statements = []
        self.commits = 0
        self.fail = fail
        for table in ('clubs', 'guests', *mirror.PULSE_TABLES):
            self.db.execute(f'CREATE TABLE {table} (id INTEGER)')
            self.db.execute(f'INSERT INTO {table} VALUES (?)', (value,))
        self.db.commit()

    def cursor(self, kind=None):
        return Cursor(self, kind)

    def begin(self):
        self.db.execute('BEGIN')

    def commit(self):
        self.commits += 1
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def values(self, table):
        return self.db.execute(f'SELECT * FROM {table}').fetchall()


@pytest.mark.parametrize('reset', [False, True])
def test_copy_commits_together_preserves_history_unless_initial_reset(reset):
    source, stage = Connection(42), Connection(7)
    counts = mirror.replace_tables(source, stage, {'clubs': ['id'], 'guests': ['id']}, reset_pulse=reset, batch_size=1)
    assert counts == {'clubs': 1, 'guests': 1}
    assert stage.commits == 1
    assert stage.values('clubs') == stage.values('guests') == [(42,)]
    assert stage.values('guest_score_history') == ([] if reset else [(7,)])
    assert 'SET TRANSACTION READ ONLY' in source.statements
    assert all(sql.startswith(('SELECT ', 'SET ', 'START TRANSACTION')) for sql in source.statements)
    assert stage.statements[-1] == 'SET FOREIGN_KEY_CHECKS=1'


def test_failure_on_second_table_rolls_back_first_table_too():
    source, stage = Connection(42), Connection(7, fail=True)
    with pytest.raises(RuntimeError):
        mirror.replace_tables(source, stage, {'clubs': ['id'], 'guests': ['id']})
    assert stage.commits == 0
    assert stage.values('clubs') == stage.values('guests') == [(7,)]
    assert stage.statements[-1] == 'SET FOREIGN_KEY_CHECKS=1'


def test_schema_plan_keeps_default_generated_timestamps_and_excludes_local_history(monkeypatch):
    names = ['clubs', 'guests', 'guest_sessions', 'guest_balance_topups', 'guest_score_history', 'guest_pulse_dirty', 'mailings']
    monkeypatch.setattr(mirror, 'inventory', lambda conn: {name: {'TABLE_TYPE': 'BASE TABLE', 'ENGINE': 'InnoDB'} for name in names})
    def columns(conn, name):
        return [dict(COLUMN_NAME='created_at', COLUMN_TYPE='timestamp', IS_NULLABLE='NO', COLUMN_DEFAULT='CURRENT_TIMESTAMP', EXTRA='DEFAULT_GENERATED')]
    monkeypatch.setattr(mirror, 'columns', columns)
    plan = mirror.make_plan(object(), object())
    assert plan['guests'] == ['created_at']
    assert 'mailings' in plan
    assert not set(plan) & {'guest_score_history', 'guest_pulse_dirty'}


def test_equal_database_names_refused_even_with_host_aliases():
    with pytest.raises(ValueError, match='equal'):
        mirror.validate_targets({'database': 'prod', 'host': 'localhost'}, {'database': 'PROD', 'host': '127.0.0.1'})


def test_cron_changes_only_stage_jobs_and_keeps_backups():
    prod = '* * * * * cd /root/cm_v2/CM_V2 && venv/bin/python scripts/process_mailings.py\n'
    stage = '* * * * * cd /root/cm_stage/CM_V2 && venv/bin/python scripts/process_mailings.py\n'
    backup = '0 3 * * * bash /root/cm_stage/CM_V2/scripts/backup_mysql.sh\n'
    unrelated = '* * * * * /root/cm_stage/CM_V2_other/run\n'
    updated, count = setup.filtered_cron(prod + stage + backup + unrelated)
    assert count == 1
    assert updated == prod + '# stage mirror disabled legacy job: ' + stage + backup + unrelated
    assert setup.filtered_cron(updated) == (updated, 0)


def test_mixed_stage_production_cron_refused():
    with pytest.raises(ValueError, match='combines'):
        setup.filtered_cron('* * * * * /root/cm_stage/CM_V2/run && /root/cm_v2/CM_V2/run\n')


def test_incompatible_schema_refused_before_copy(monkeypatch):
    source, stage = object(), object()
    monkeypatch.setattr(mirror, 'inventory', lambda conn: {'clubs': {'TABLE_TYPE': 'BASE TABLE', 'ENGINE': 'InnoDB'}})
    def columns(conn, name):
        return [dict(COLUMN_NAME='id', COLUMN_TYPE='int' if conn is source else 'bigint', IS_NULLABLE='NO', COLUMN_DEFAULT=None, EXTRA='')]
    monkeypatch.setattr(mirror, 'columns', columns)
    with pytest.raises(ValueError, match='Incompatible stage column'):
        mirror.make_plan(source, stage)


def test_systemd_inventory_skips_templates_but_includes_loaded_instances(monkeypatch):
    from types import SimpleNamespace
    def run(*args, **kwargs):
        if args[1] == 'list-unit-files':
            return SimpleNamespace(stdout='getty@.service static\nclubmodule-stage.service enabled\n')
        return SimpleNamespace(stdout='getty@tty1.service loaded active running Getty\nclubmodule-stage-worker@1.service loaded active running Worker\n')
    monkeypatch.setattr(setup, 'run', run)
    assert setup.unit_names('service') == ['clubmodule-stage-worker@1.service', 'clubmodule-stage.service', 'getty@tty1.service']


def test_systemctl_failure_reports_operation_without_captured_secrets(monkeypatch):
    import subprocess
    def failing(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, output='SECRET', stderr='SECRET')
    monkeypatch.setattr(setup.subprocess, 'run', failing)
    with pytest.raises(ValueError, match='systemctl show failed') as error:
        setup.run('systemctl', 'show', 'sample.service', capture_output=True)
    assert 'sample.service' in str(error.value)
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('keys', [['id'], []])
def test_bounded_pages_copy_every_row_once(monkeypatch, keys):
    monkeypatch.setattr(mirror, 'primary_key', lambda conn, table: keys)
    source, stage = Connection(1), Connection(99)
    source.db.executemany('INSERT INTO guests VALUES (?)', [(2,), (5,), (8,), (9,)])
    source.db.commit()
    assert mirror.replace_tables(source, stage, {'guests': ['id']}, batch_size=2) == {'guests': 5}
    assert stage.values('guests') == [(1,), (2,), (5,), (8,), (9,)]
    selects = [sql for sql in source.statements if sql.startswith('SELECT')]
    assert len(selects) == 3
    assert all('LIMIT %s' in sql for sql in selects)


def test_composite_key_pages_do_not_skip_equal_first_key(monkeypatch):
    monkeypatch.setattr(mirror, 'primary_key', lambda conn, table: ['club', 'guest'])
    source = Connection(1)
    source.db.execute('CREATE TABLE events (club INTEGER, guest INTEGER)')
    expected = [(1, 1), (1, 3), (1, 9), (2, 1), (2, 2)]
    source.db.executemany('INSERT INTO events VALUES (?, ?)', expected)
    source.db.commit()
    batches = list(mirror.source_batches(source, 'events', ['club', 'guest'], 2))
    assert [row for batch in batches for row in batch] == expected


def test_cleanup_connection_error_does_not_hide_original_copy_error(monkeypatch):
    source, stage = Connection(42), Connection(7, fail=True)
    original = stage.rollback
    calls = 0
    def rollback():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise mirror.pymysql.InterfaceError(0, '')
        original()
    monkeypatch.setattr(stage, 'rollback', rollback)
    with pytest.raises(RuntimeError, match='injected insert failure'):
        mirror.replace_tables(source, stage, {'guests': ['id']})


def test_safe_error_keeps_mysql_code_but_omits_private_values():
    assert mirror.safe_error(mirror.pymysql.OperationalError(2013, 'private row')) == 'OperationalError (code 2013)'
