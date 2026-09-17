from scripts.check_release_migrations import PRODUCTION_ANCHORS, inspect_migrations
from scripts.check_release_tree import inspect_production_units


def test_release_migration_set_is_well_formed_and_keeps_production_anchors():
    revisions, errors = inspect_migrations()

    assert errors == []
    assert PRODUCTION_ANCHORS.issubset(revisions)


def test_production_units_do_not_reference_stage_runtime():
    assert inspect_production_units() == []
