import pytest

from turbine_troubleshooter.helpers import is_test_mode
from turbine_troubleshooter.settings import (
    ENV_VARS,
    NOISE_FILTERS,
    SETTINGS,
    setup,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(f"TROUBLESHOOTER_{var}", raising=False)
    monkeypatch.delenv("TROUBLESHOOTER_NAME", raising=False)


def test_setup_reads_its_own_environment(monkeypatch):
    for var, value in {
        "BOT_NAME": "Site Troubleshooter",
        "WTG_PREFIX": "ST",
        "BOT_TOKEN": "123:abc",
        "OWNER_ID": "42",
        "ALERTS_CHAT_ID": "-100",
        "DB_URL": "mysql://u:p@h/ts",
        "TIMEZONE": "UTC",
        "CEFAS_BUOY": "BUOY1",
        "WINDQUEST_LOCATION": "Site 1",
        "WINDQUEST_API_KEY": "key",
        "WINDQUEST_API_TOKEN": "tok",
    }.items():
        monkeypatch.setenv(var, value)

    setup()

    assert (SETTINGS.name, SETTINGS.wtg_prefix) == ("Site Troubleshooter", "ST")
    assert (SETTINGS.token, SETTINGS.owner_id) == ("123:abc", "42")
    assert (SETTINGS.alerts_chat_id, SETTINGS.timezone) == ("-100", "UTC")
    assert SETTINGS.db_url == "mysql://u:p@h/ts"
    assert (SETTINGS.cefas_buoy, SETTINGS.windquest_location) == ("BUOY1", "Site 1")
    assert (SETTINGS.windquest_api_key, SETTINGS.windquest_api_token) == ("key", "tok")


def test_the_old_names_are_no_longer_read(monkeypatch):
    monkeypatch.setattr(SETTINGS, "token", None)
    monkeypatch.setattr(SETTINGS, "name", "Troubleshooter")
    monkeypatch.setattr(SETTINGS, "windquest_api_key", None)
    monkeypatch.setenv("TROUBLESHOOTER_BOT_TOKEN", "123:old")
    monkeypatch.setenv("TROUBLESHOOTER_NAME", "Old Name")

    setup()

    assert (SETTINGS.token, SETTINGS.name) == (None, "Troubleshooter")

    monkeypatch.setenv("WINDQUEST_API_KEY", "old-key")

    setup("TROUBLESHOOTER_")

    assert SETTINGS.windquest_api_key is None


def test_a_host_prefix_reads_only_the_prefixed_names(monkeypatch):
    monkeypatch.setattr(SETTINGS, "token", None)
    monkeypatch.setattr(SETTINGS, "owner_id", None)
    monkeypatch.setenv("BOT_TOKEN", "123:host-own")
    monkeypatch.setenv("SITE_OWNER_ID", "42")

    setup("SITE_")

    assert SETTINGS.token is None
    assert SETTINGS.owner_id == "42"
    assert SETTINGS.env_prefix == "SITE_"


def test_a_host_reads_the_prefixed_windquest_names(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTER_WINDQUEST_API_KEY", "new-key")

    setup("TROUBLESHOOTER_")

    assert SETTINGS.windquest_api_key == "new-key"


def test_setup_arguments_override_environment(monkeypatch):
    monkeypatch.setenv("BOT_NAME", "From Env")

    setup(name="From Code", files_dir="/media")

    assert SETTINGS.name == "From Code"
    assert SETTINGS.files_dir == "/media"


def test_blank_environment_values_are_ignored(monkeypatch):
    monkeypatch.setattr(SETTINGS, "name", "Kept")
    monkeypatch.setenv("BOT_NAME", "")

    setup()

    assert SETTINGS.name == "Kept"


def test_default_noise_filters_cover_network_blips():
    assert "Query is too old" in NOISE_FILTERS
    assert "Timed out" in NOISE_FILTERS


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("on", True), (True, True)]
    + [("0", False), ("false", False), ("", False), (False, False), (None, False)],
)
def test_test_mode_values(monkeypatch, value, expected):
    monkeypatch.setattr(SETTINGS, "test_mode", value)

    assert is_test_mode() is expected


def test_test_mode_is_off_without_the_variable(monkeypatch):
    monkeypatch.setattr(SETTINGS, "test_mode", False)
    monkeypatch.delenv("DYNO", raising=False)

    setup()

    assert is_test_mode() is False


def test_test_mode_is_read_from_the_environment(monkeypatch):
    monkeypatch.setattr(SETTINGS, "test_mode", False)
    monkeypatch.setenv("TEST_MODE", "1")

    setup()

    assert is_test_mode() is True
