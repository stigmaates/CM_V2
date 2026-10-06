from pathlib import Path

import pytest

from app.integrations.stage import validate_stage_target


def target(**changes):
    args = dict(root=Path('/root/cm_stage/CM_V2'),
                stage={'DB_HOST':'db','DB_PORT':'3306','DB_NAME':'stage_db'},
                production={'DB_HOST':'db','DB_NAME':'default_db'},
                loaded=('db',3306,'stage_db'),outbound_blocked=True)
    args.update(changes)
    return validate_stage_target(**args)


@pytest.mark.parametrize('mode', ['stage','staging','development','production'])
def test_flask_mode_does_not_change_verified_stage_identity(monkeypatch, mode):
    monkeypatch.setenv('APP_ENV', mode)
    assert target() is None


@pytest.mark.parametrize('changes', [
    {'root':Path('/root/cm_v2/CM_V2')},
    {'outbound_blocked':False},
    {'production':{'DB_HOST':'alias','DB_NAME':'STAGE_DB'}},
    {'production':{}},
    {'stage':{}},
    {'loaded':('db',3306,'default_db')},
    {'loaded':('other',3306,'stage_db')},
    {'loaded':('db',3307,'stage_db')},
])
def test_stage_label_never_bypasses_path_database_or_outbound_guards(monkeypatch, changes):
    monkeypatch.setenv('APP_ENV','stage')
    with pytest.raises(ValueError):
        target(**changes)
