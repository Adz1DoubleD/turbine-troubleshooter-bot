from types import SimpleNamespace

SETTINGS = SimpleNamespace(
    name="Troubleshooter",
    wtg_prefix="",
    token=None,
    owner_id=None,
    alerts_chat_id=None,
    timezone="Europe/London",
    noise_filters=(),
    notify_settings={},
    content=None,
    files_dir=None,
    weather_button=None,
)


def setup(**options):
    unknown = set(options) - set(vars(SETTINGS))
    if unknown:
        raise TypeError(f"Unknown troubleshooter settings: {sorted(unknown)}")
    for name, value in options.items():
        setattr(SETTINGS, name, value)
