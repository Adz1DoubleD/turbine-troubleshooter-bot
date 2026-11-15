# troubleshooter-bot

A Telegram bot for field technicians: search fault codes and spare parts, look up turbine info and IO board pin-outs, and browse reference content (text, documents, photos). Access is by approval, with admins who can add and edit codes and parts.

It is a Python package that a host application installs and starts. All site-specific content and documents are supplied by the host at runtime; nothing private lives in this repo.

## Use

```python
from troubleshooter import start_troubleshooter_bot
from troubleshooter.db import close_db, init_troubleshooter_db
from troubleshooter.settings import setup

setup(
    name="Acme Troubleshooter",
    wtg_prefix="WT",
    token=BOT_TOKEN,
    owner_id=OWNER_CHAT_ID,
    alerts_chat_id=ALERTS_CHAT_ID,
    timezone="Europe/London",
    files_dir=Path("media"),
)

await init_troubleshooter_db(main_application)
await start_troubleshooter_bot(main_application)
...
await close_db()
```

| Setting | Purpose |
|---|---|
| `name` | Shown in menus and messages ("*name* Bot") |
| `wtg_prefix` | Prefix for turbine IDs, e.g. `WT` turns `A5` into `WTA05` |
| `token` | Telegram bot token |
| `owner_id` | Telegram ID of the owner (approves access and admins) |
| `alerts_chat_id` | Chat for new-user, access-request and change notifications |
| `timezone` | Used for edit timestamps |
| `noise_filters` | Error messages to ignore (network blips etc.) |
| `notify_settings` | Dict with `troubleshooter_notify_added/edited/deleted` toggles |
| `content` | Fallback content when the database has none (see below) |
| `files_dir` | Folder that `file:` references in the content resolve against |
| `cefas_buoy` | Cefas WaveNet buoy ID for sea state (e.g. `ABCDEFGH`); enables 🌦 Work Weather |
| `windquest_api_key`, `windquest_api_token` | WindQuest API credentials for wind, lightning and tides |
| `windquest_location` | Preferred WindQuest forecast location name (falls back to the main location) |

## Database

MySQL, via `TROUBLESHOOTER_DB_URL` (falls back to `JAWSDB_URL`), e.g. `mysql://user:pass@host:3306/db`. Tables are created on first start: `codes`, `parts`, `users`, one table per IO board, and `content`.

## Content

The menus, turbine map, IO boards and part-search hints are loaded from the `content` table: one row per item (`MODULES_MAP`, `WTG_MAP`, `IO_BOARDS`, `PART_ACCESSORIES`), stored as JSON text. Documents and photos are referenced as `file:<path relative to files_dir>`. See [`troubleshooter/example_content.py`](troubleshooter/example_content.py) for the shape.

## Development

```bash
pip install -e ".[dev]"
pre-commit run --all-files
pytest
```

CI fails if any document, image or spreadsheet file is committed, or if the package imports anything from a host application.
