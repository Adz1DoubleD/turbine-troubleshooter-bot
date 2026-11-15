# troubleshooter-bot

A Telegram bot for field technicians: search fault codes and spare parts, look up turbine info and IO board pin-outs, and browse reference content (text, documents, photos). Access is by approval, with admins who can add and edit codes and parts.

It is a Python package that a host application installs and starts, or that runs on its own. All site-specific content and documents are supplied by the host at runtime; nothing private lives in this repo.

## Use

Inside a host application:

```python
from troubleshooter import start_troubleshooter_bot, stop_troubleshooter_bot

await start_troubleshooter_bot(share_with=main_application, files_dir=Path("media"))
...
await stop_troubleshooter_bot()
```

`share_with` is optional: pass the host's `Application` when the host shows the troubleshooter menus too, so both bots use the same loaded codes, parts and users.

On its own (reads a `.env` in the current folder):

```bash
python -m troubleshooter
```

Standalone also uses `TROUBLESHOOTER_FILES_DIR` (default `media`) and `TROUBLESHOOTER_SENTRY_DSN` (Sentry is off when unset).

The settings below are read from the environment; any keyword passed to `start_troubleshooter_bot()` overrides the environment.

| Setting | Environment variable | Purpose |
|---|---|---|
| `name` | `TROUBLESHOOTER_NAME` | Shown in menus and messages ("*name* Bot"). Default `Troubleshooter` |
| `wtg_prefix` | `TROUBLESHOOTER_WTG_PREFIX` | Prefix for turbine IDs, e.g. `WT` turns `A5` into `WTA05` |
| `token` | `TROUBLESHOOTER_BOT_TOKEN` | Telegram bot token |
| `owner_id` | `TROUBLESHOOTER_OWNER_ID` | Telegram ID of the owner (approves access and admins) |
| `alerts_chat_id` | `TROUBLESHOOTER_ALERTS_CHAT_ID` | Chat for new-user, access-request and change notifications |
| `timezone` | `TROUBLESHOOTER_TIMEZONE` | Used for edit timestamps and weather. Default `Europe/London` |
| `cefas_buoy` | `TROUBLESHOOTER_CEFAS_BUOY` | Cefas WaveNet buoy ID for sea state; enables 🌦 Work Weather |
| `windquest_location` | `TROUBLESHOOTER_WINDQUEST_LOCATION` | Preferred WindQuest forecast location (falls back to the main location) |
| `windquest_api_key`, `windquest_api_token` | `WINDQUEST_API_KEY`, `WINDQUEST_API_TOKEN` | WindQuest credentials for wind, lightning and tides |
| `files_dir` | — | Folder that `file:` references in the content resolve against |
| `content` | — | Fallback content when the database has none (see below) |
| `noise_filters` | — | Error messages to ignore. Defaults to common network blips |

## Database

MySQL, via `TROUBLESHOOTER_DB_URL` (falls back to `JAWSDB_URL`), e.g. `mysql://user:pass@host:3306/db`. Tables are created on first start: `codes`, `parts`, `users`, one table per IO board, `content`, and `settings`.

`settings` holds the owner's *Notify Users* toggles (`notify_added`, `notify_edited`, `notify_deleted`; on unless a row says `0`), set from **Admin Panel → 🔔 Notify Users**. When one is off, that kind of code or part change is only sent to admins.

## Content

The menus, turbine map, IO boards and part-search hints are loaded from the `content` table: one row per item (`MODULES_MAP`, `WTG_MAP`, `IO_BOARDS`, `PART_ACCESSORIES`), stored as JSON text. Documents and photos are referenced as `file:<path relative to files_dir>`. See [`troubleshooter/example_content.py`](troubleshooter/example_content.py) for the shape.

## Development

```bash
pip install -e ".[dev]"
pre-commit run --all-files
pytest
```

CI fails if any document, image or spreadsheet file is committed, or if the package imports anything from a host application.
