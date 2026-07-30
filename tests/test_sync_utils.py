from scripts.sync_utils import is_service_enabled


def test_is_service_enabled_defaults_to_enabled():
    assert is_service_enabled({}) is True
    assert is_service_enabled({"service_enabled": None}) is True


def test_is_service_enabled_reads_disabled_flag():
    assert is_service_enabled({"service_enabled": 0}) is False
    assert is_service_enabled({"service_enabled": "0"}) is False
    assert is_service_enabled({"service_enabled": 1}) is True
