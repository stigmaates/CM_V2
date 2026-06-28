import importlib


def test_product_readiness_migration_exports_revision_and_upgrade():
    migration = importlib.import_module("migrations.versions.0001_product_readiness_schema")

    assert migration.revision == "0001_product_readiness_schema"
    assert callable(migration.upgrade)
