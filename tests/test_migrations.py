import importlib

import scripts.migrate as migrate_script


def test_product_readiness_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0001_product_readiness_schema")

    assert migration.revision == "0001_product_readiness_schema"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "background_job_runs" in value for value in migration.upgrade.__code__.co_consts
    )


def test_background_job_locks_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0002_background_job_locks")

    assert migration.revision == "0002_background_job_locks"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "background_job_locks" in value for value in migration.upgrade.__code__.co_consts
    )


def test_operational_alert_notifications_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0003_operational_alert_notifications")

    assert migration.revision == "0003_operational_alert_notifications"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "operational_alert_notifications" in value
        for value in migration.upgrade.__code__.co_consts
    )


def test_admin_user_last_login_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0004_admin_user_last_login")

    assert migration.revision == "0004_admin_user_last_login"
    assert callable(migration.upgrade)
    assert any(isinstance(value, str) and "last_login_at" in value for value in migration.upgrade.__code__.co_consts)


def test_giveaway_tokens_and_personal_messages_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0005_giveaway_tokens_and_personal_messages")

    assert migration.revision == "0005_giveaway_tokens_and_personal_messages"
    assert callable(migration.upgrade)
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("message_text" in value for value in constants)
    assert any("token_amount" in value for value in constants)


def test_guest_balance_topups_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0006_guest_balance_topups")

    assert migration.revision == "0006_guest_balance_topups"
    assert callable(migration.upgrade)
    assert any(
        isinstance(value, str) and "guest_balance_topups" in value for value in migration.upgrade.__code__.co_consts
    )


def test_club_service_enabled_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0007_club_service_enabled")

    assert migration.revision == "0007_club_service_enabled"
    assert callable(migration.upgrade)
    assert any(isinstance(value, str) and "service_enabled" in value for value in migration.upgrade.__code__.co_consts)


def test_expiring_cm_bonuses_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0008_expiring_cm_bonuses")

    assert migration.revision == "0008_expiring_cm_bonuses"
    assert callable(migration.upgrade)
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("expires_at" in value for value in constants)
    assert any("idx_cm_bonus_expiration" in value for value in constants)


def test_guest_lookup_indexes_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0009_guest_lookup_indexes")

    assert migration.revision == "0009_guest_lookup_indexes"
    assert callable(migration.upgrade)
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("idx_guests_club_guest" in value for value in constants)
    assert any("idx_guests_club_phone" in value for value in constants)


def test_dashboard_performance_indexes_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0010_dashboard_performance_indexes")

    assert migration.revision == "0010_dashboard_performance_indexes"
    assert callable(migration.upgrade)
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("idx_guest_sessions_club_date_guest" in value for value in constants)
    assert any("idx_guest_wheel_spins_club_date_guest" in value for value in constants)
    assert any("idx_user_portrait_club_crm_telegram" in value for value in constants)


def test_crm_status_pulse_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0011_crm_status_pulse")

    assert migration.revision == "0011_crm_status_pulse"
    assert callable(migration.upgrade)
    constants = [value for value in migration.upgrade.__code__.co_consts if isinstance(value, str)]
    assert any("crm_status_changes" in value for value in constants)
    assert any("idx_auto_mailing_logs_guest_created" in value for value in constants)


class _Cursor:
    def __init__(self):
        self.applied = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if query.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return
        if query == "SELECT revision FROM schema_migrations":
            return
        if query.startswith("INSERT INTO schema_migrations"):
            self.applied = True

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("dry-run should not rollback")

    def close(self):
        self.closed = True


def test_migrate_dry_run_lists_pending_without_applying(monkeypatch, capsys):
    conn = _Connection()

    monkeypatch.setattr(migrate_script, "get_db_connection", lambda: conn)

    assert migrate_script.migrate(dry_run=True) == 0

    output = capsys.readouterr().out
    assert "Pending migrations:" in output
    assert "0001_product_readiness_schema" in output
    assert conn.cursor_obj.applied is False
    assert conn.committed is False
    assert conn.closed is True
