import pytest

from turbine_troubleshooter.helpers import is_test_mode
from turbine_troubleshooter.settings import (
    ENV_VARS,
    NOISE_FILTERS,
    OLD_ENV_VARS,
    SETTINGS,
    setup,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in [*ENV_VARS.values(), *OLD_ENV_VARS.values()]:
        monkeypatch.delenv(var, raising=False)


def test_setup_reads_its_own_environment(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTER_NAME", "Site Troubleshooter")
    monkeypatch.setenv("TROUBLESHOOTER_WTG_PREFIX", "ST")
    monkeypatch.setenv("TROUBLESHOOTER_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TROUBLESHOOTER_OWNER_ID", "42")
    monkeypatch.setenv("TROUBLESHOOTER_ALERTS_CHAT_ID", "-100")
    monkeypatch.setenv("TROUBLESHOOTER_TIMEZONE", "UTC")
    monkeypatch.setenv("TROUBLESHOOTER_CEFAS_BUOY", "BUOY1")
    monkeypatch.setenv("TROUBLESHOOTER_WINDQUEST_LOCATION", "Site 1")
    monkeypatch.setenv("TROUBLESHOOTER_WINDQUEST_API_KEY", "key")
    monkeypatch.setenv("TROUBLESHOOTER_WINDQUEST_API_TOKEN", "tok")

    setup()

    assert (SETTINGS.name, SETTINGS.wtg_prefix) == ("Site Troubleshooter", "ST")
    assert (SETTINGS.token, SETTINGS.owner_id) == ("123:abc", "42")
    assert (SETTINGS.alerts_chat_id, SETTINGS.timezone) == ("-100", "UTC")
    assert (SETTINGS.cefas_buoy, SETTINGS.windquest_location) == ("BUOY1", "Site 1")
    assert (SETTINGS.windquest_api_key, SETTINGS.windquest_api_token) == ("key", "tok")


def test_the_old_windquest_names_still_work(monkeypatch):
    monkeypatch.setattr(SETTINGS, "windquest_api_key", None)
    monkeypatch.setattr(SETTINGS, "windquest_api_token", None)
    monkeypatch.setenv("WINDQUEST_API_KEY", "old-key")
    monkeypatch.setenv("WINDQUEST_API_TOKEN", "old-tok")

    setup()

    assert (SETTINGS.windquest_api_key, SETTINGS.windquest_api_token) == (
        "old-key",
        "old-tok",
    )


def test_the_new_windquest_names_win(monkeypatch):
    monkeypatch.setenv("WINDQUEST_API_KEY", "old-key")
    monkeypatch.setenv("TROUBLESHOOTER_WINDQUEST_API_KEY", "new-key")

    setup()

    assert SETTINGS.windquest_api_key == "new-key"


def test_setup_arguments_override_environment(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTER_NAME", "From Env")

    setup(name="From Code", files_dir="/media")

    assert SETTINGS.name == "From Code"
    assert SETTINGS.files_dir == "/media"


def test_blank_environment_values_are_ignored(monkeypatch):
    monkeypatch.setattr(SETTINGS, "name", "Kept")
    monkeypatch.setenv("TROUBLESHOOTER_NAME", "")

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
    monkeypatch.setenv("TROUBLESHOOTER_TEST_MODE", "1")

    setup()

    assert is_test_mode() is True
