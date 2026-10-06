from importlib import import_module

import pytest

from scripts.mirror_production_to_stage import compatible_column_type

migration = import_module("migrations.versions.0055_session_timestamp_precision")


class SchemaCursor:
    def __init__(self, start=None, stop=None):
        standard = dict(column_type="datetime", is_nullable="YES", column_default=None, extra="", comment="")
        self.columns = {"date_start": dict(standard, **(start or {})), "date_stop": dict(standard, **(stop or {}))}
        self.calls = []
        self.selected = None

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "information_schema" in sql:
            self.selected = self.columns[params[0]]
        else:
            for column in self.columns.values():
                column["column_type"] = "datetime(6)"

    def fetchone(self):
        return self.selected

    @property
    def alterations(self):
        return [call for call in self.calls if call[0].startswith("ALTER")]


def test_precision_migration_keeps_nullability_and_is_repeatable():
    cursor = SchemaCursor(start={"is_nullable": "NO"})
    migration.upgrade(cursor)
    migration.upgrade(cursor)
    assert len(cursor.alterations) == 1
    sql, params = cursor.alterations[0]
    assert "date_start DATETIME(6) NOT NULL" in sql
    assert "date_stop DATETIME(6) NULL DEFAULT NULL" in sql
    assert params == ("", "")


def test_precision_migration_preserves_defaults_comments_and_update_expression():
    cursor = SchemaCursor(
        start=dict(
            column_default="CURRENT_TIMESTAMP",
            extra="DEFAULT_GENERATED on update CURRENT_TIMESTAMP",
            comment="source's timestamp",
        ),
        stop=dict(column_default="2020-01-01 00:00:00"),
    )
    migration.upgrade(cursor)
    sql, params = cursor.alterations[0]
    assert "DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)" in sql
    assert params == ("source's timestamp", "2020-01-01 00:00:00", "")
    assert "source's" not in sql


def test_unknown_second_column_is_rejected_before_any_auto_committing_ddl():
    cursor = SchemaCursor(stop={"column_type": "timestamp"})
    with pytest.raises(RuntimeError, match="type"):
        migration.upgrade(cursor)
    assert cursor.alterations == []


@pytest.mark.parametrize(
    "source,target,allowed",
    [
        ("datetime", "datetime(6)", True),
        ("datetime(3)", "datetime(6)", True),
        ("datetime(6)", "datetime", False),
        ("datetime(6)", "datetime(3)", False),
        ("timestamp", "datetime(6)", False),
        ("int", "bigint", False),
        ("int", "int", True),
    ],
)
def test_stage_mirror_only_accepts_lossless_timestamp_widening(source, target, allowed):
    assert compatible_column_type(source, target) is allowed
