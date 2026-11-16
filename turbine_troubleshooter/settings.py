import os
from types import SimpleNamespace

os.environ.setdefault("PTB_TIMEDELTA", "1")

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
    files_dir=None,
    cefas_buoy=None,
    windquest_api_key=None,
    windquest_api_token=None,
    windquest_location=None,
)


def setup(**options):
    unknown = set(options) - set(vars(SETTINGS))
    if unknown:
        raise TypeError(f"Unknown troubleshooter settings: {sorted(unknown)}")
    for name, var in ENV_VARS.items():
        value = os.environ.get(var)
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
