import os
from types import SimpleNamespace

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
    "name": "TROUBLESHOOTER_NAME",
    "wtg_prefix": "TROUBLESHOOTER_WTG_PREFIX",
    "token": "TROUBLESHOOTER_BOT_TOKEN",
    "owner_id": "TROUBLESHOOTER_OWNER_ID",
    "alerts_chat_id": "TROUBLESHOOTER_ALERTS_CHAT_ID",
    "timezone": "TROUBLESHOOTER_TIMEZONE",
    "cefas_buoy": "TROUBLESHOOTER_CEFAS_BUOY",
    "windquest_location": "TROUBLESHOOTER_WINDQUEST_LOCATION",
    "windquest_api_key": "TROUBLESHOOTER_WINDQUEST_API_KEY",
    "windquest_api_token": "TROUBLESHOOTER_WINDQUEST_API_TOKEN",
    "test_mode": "TROUBLESHOOTER_TEST_MODE",
    "announce_updates": "TROUBLESHOOTER_ANNOUNCE_UPDATES",
    "files_repo": "TROUBLESHOOTER_FILES_REPO",
    "files_repo_branch": "TROUBLESHOOTER_FILES_REPO_BRANCH",
    "files_repo_token": "TROUBLESHOOTER_FILES_REPO_TOKEN",
}
OLD_ENV_VARS = {
    "windquest_api_key": "WINDQUEST_API_KEY",
    "windquest_api_token": "WINDQUEST_API_TOKEN",
}

SETTINGS = SimpleNamespace(
    name="Troubleshooter",
    wtg_prefix="",
    token=None,
    owner_id=None,
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


def setup(**options):
    unknown = set(options) - set(vars(SETTINGS)) | (
        set(options) & {"content", "menu", "notify_settings"}
    )
    if unknown:
        raise TypeError(f"Unknown troubleshooter settings: {sorted(unknown)}")
    for name, var in ENV_VARS.items():
        value = os.environ.get(var) or os.environ.get(OLD_ENV_VARS.get(name, ""))
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
