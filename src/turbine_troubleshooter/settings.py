"""Start-up settings and their environment variables."""

import os
from types import SimpleNamespace
from typing import Any

NOISE_FILTERS = (
    "httpx.ReadError",
    "RemoteProtocolError",
    "Timed out",
    "Query is too old",
    "query id is invalid",
    "Task was destroyed",
    "Bad Gateway",
    "Conflict: terminated by other getUpdates",
    "Service Unavailable",
    "Network is unreachable",
    "ConnectError",
    "Request timeout",
    "Internal Server Error",
    "Gateway Timeout",
    "Message is not modified",
    "BrokenPipeError",
    "Broken pipe",
)

ENV_VARS = {
    "name": "BOT_NAME",
    "wtg_prefix": "WTG_PREFIX",
    "token": "BOT_TOKEN",
    "owner_id": "OWNER_ID",
    "alerts_chat_id": "ALERTS_CHAT_ID",
    "db_url": "DB_URL",
    "timezone": "TIMEZONE",
    "cefas_buoy": "CEFAS_BUOY",
    "windquest_location": "WINDQUEST_LOCATION",
    "windquest_api_key": "WINDQUEST_API_KEY",
    "windquest_api_token": "WINDQUEST_API_TOKEN",
    "test_mode": "TEST_MODE",
    "announce_updates": "ANNOUNCE_UPDATES",
    "files_repo": "FILES_REPO",
    "files_repo_branch": "FILES_REPO_BRANCH",
    "files_repo_token": "FILES_REPO_TOKEN",
}

SETTINGS = SimpleNamespace(
    name="Troubleshooter",
    wtg_prefix="",
    token=None,
    owner_id=None,
    db_url=None,
    env_prefix="",
    alerts_chat_id=None,
    timezone="Europe/London",
    noise_filters=NOISE_FILTERS,
    notify_settings={},
    content=None,
    menu=None,
    files_dir=None,
    cefas_buoy=None,
    windquest_api_key=None,
    windquest_api_token=None,
    windquest_location=None,
    test_mode=False,
    announce_updates=True,
    files_repo=None,
    files_repo_branch="main",
    files_repo_token=None,
)

NOTIFY_DEFAULTS = {"added": 1, "edited": 0, "deleted": 1}


def setup(env_prefix: str = "", **options: Any) -> None:
    unknown = set(options) - set(vars(SETTINGS)) | (
        set(options) & {"content", "menu", "notify_settings", "env_prefix"}
    )
    if unknown:
        raise TypeError(f"Unknown troubleshooter settings: {sorted(unknown)}")
    SETTINGS.env_prefix = env_prefix
    for name, var in ENV_VARS.items():
        value = os.environ.get(f"{env_prefix}{var}")
        if value:
            setattr(SETTINGS, name, value)
    for name, value in options.items():
        setattr(SETTINGS, name, value)


SKIPPED_WORDS = [
    "bracket",
    "support",
    "hose",
    "pipe",
    "cover",
    "plate",
    "cable",
    "seal",
    "kit",
    "fitting",
]
