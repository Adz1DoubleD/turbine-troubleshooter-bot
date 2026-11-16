# turbine-troubleshooter-bot

A Telegram bot for field technicians: search fault codes and spare parts, look up turbine info and IO board pin-outs, and browse reference content (text, documents, photos). Access is by approval, with admins who can add and edit codes and parts.

It is a Python package that a host application installs and starts, or that runs on its own. All site-specific content and documents are supplied by the host at runtime; nothing private lives in this repo.

## Install

```bash
pip install turbine-troubleshooter-bot
```

The package installs as `turbine-troubleshooter-bot` and imports as `turbine_troubleshooter`.

## Use

Inside a host application:

```python
from turbine_troubleshooter import start_troubleshooter_bot, stop_troubleshooter_bot

await start_troubleshooter_bot(share_with=main_application, files_dir=Path("media"))
...
await stop_troubleshooter_bot()
```

`share_with` is optional: pass the host's `Application` when the host shows the troubleshooter menus too, so both bots use the same loaded codes, parts and users.

On its own (reads a `.env` in the current folder):

```bash
python -m turbine_troubleshooter
```

Standalone also uses `TROUBLESHOOTER_FILES_DIR` (default `media`) and `TROUBLESHOOTER_SENTRY_DSN` (Sentry is off when unset).

The settings below are read from the environment; any keyword passed to `start_troubleshooter_bot()` overrides the environment.

| Setting | Environment variable | Purpose |
|---|---|---|
| `name` | `TROUBLESHOOTER_NAME` | Shown in menus and messages ("*name* Bot"). Default `Troubleshooter` |
| `wtg_prefix` | `TROUBLESHOOTER_WTG_PREFIX` | Prefix for turbine IDs, e.g. `WT` turns `A5` into `WTA05` |
| `token` | `TROUBLESHOOTER_BOT_TOKEN` | Telegram bot token |
| `owner_id` | `TROUBLESHOOTER_OWNER_ID` | Telegram ID of the owner (approves access and admins) |
| `alerts_chat_id` | `TROUBLESHOOTER_ALERTS_CHAT_ID` | Chat for new-user, access-request and change notifications. Defaults to the owner |
| `timezone` | `TROUBLESHOOTER_TIMEZONE` | Used for edit timestamps and weather. Default `Europe/London` |
| `cefas_buoy` | `TROUBLESHOOTER_CEFAS_BUOY` | Cefas WaveNet buoy ID for sea state; enables 🌦 Work Weather |
| `windquest_location` | `TROUBLESHOOTER_WINDQUEST_LOCATION` | Preferred WindQuest forecast location (falls back to the main location) |
| `windquest_api_key`, `windquest_api_token` | `WINDQUEST_API_KEY`, `WINDQUEST_API_TOKEN` | WindQuest credentials for wind, lightning and tides |
| `files_dir` | — | Folder that `file:` references in the content resolve against |
| `content` | — | Fallback content when the database has none (see below) |
| `noise_filters` | — | Error messages to ignore. Defaults to common network blips |

## Database

MySQL, via `TROUBLESHOOTER_DB_URL` (falls back to `JAWSDB_URL`), e.g. `mysql://user:pass@host:3306/db`. Tables are created on first start: `codes`, `parts`, `users`, one table per IO board, `content`, `settings`, `requests` (access and admin requests waiting for the owner) and `suggestions` (content suggestions waiting for the owner).

### Content suggestions

Approved users can suggest a note, a PDF or photo, or a file with text, from **📝 Suggest Content** on the main menu. Text sent with a file is shown as its caption, so it's limited to Telegram's 1024 characters. It waits in **Admin Panel → 📝 Suggestions** until the owner approves or rejects it. Nothing reaches other users before that.

- **Text** goes live as soon as it's approved: the bot writes it into the `content` table.
- **A PDF or photo** adds its menu item straight away, pointing at a `file:` path in `files_dir`, and the bot sends the owner the file with the exact path to save it as. Until the file is uploaded, the item says the document isn't available. Files go in the host's files folder, as with any other document.

PDFs and photos can only be sent to the troubleshooter bot itself, up to 20 MB. A host showing the menus through `share_with` takes text suggestions only.

`settings` holds the owner's *Notify Users* toggles (`notify_added`, `notify_edited`, `notify_deleted`; on unless a row says `0`), set from **Admin Panel → 🔔 Notify Users**. When one is off, that kind of code or part change is only sent to admins.

## Content

The menus, turbine map, IO boards and part-search hints are loaded from the `content` table: one row per item (`MODULES_MAP`, `WTG_MAP`, `IO_BOARDS`, `PART_ACCESSORIES`), stored as JSON text. Documents and photos are referenced as `file:<path relative to files_dir>`. See [`turbine_troubleshooter/example_content.py`](turbine_troubleshooter/example_content.py) for the shape.

## Run it yourself

You need Python 3.12+, a MySQL database and your own test bot from [@BotFather](https://t.me/BotFather). Your copy uses its own bot and database, so it never touches anyone else's.

Any MySQL works (a local install, or a free hosted one such as JawsDB). The `docker run` line below is the quickest way if you have [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed; skip it otherwise.

```bash
git clone https://github.com/Adz1DoubleD/turbine-troubleshooter-bot
cd turbine-troubleshooter-bot
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -e ".[dev]"

docker run -d --name ts-db -p 3306:3306 -e MYSQL_ROOT_PASSWORD=dev -e MYSQL_DATABASE=ts mysql:8

cp .env.example .env               # Windows: copy .env.example .env
```

In `.env`, set these three (the bot refuses to start and lists any that are missing):
- `TROUBLESHOOTER_BOT_TOKEN`: your test bot's token.
- `TROUBLESHOOTER_OWNER_ID`: your Telegram user ID (message [@userinfobot](https://t.me/userinfobot) to find it).
- `TROUBLESHOOTER_DB_URL`: your MySQL database.

Everything else is optional. Access requests, content suggestions and change notices go to `TROUBLESHOOTER_ALERTS_CHAT_ID`, or to the owner when it isn't set. Then:

```bash
python -m turbine_troubleshooter
```

Run your own copy on its own bot token: a token can only be used by one running bot at a time, so sharing the live one gives "Conflict" errors.

Open your test bot in Telegram and send `/start`. As the owner you get the admin panel. Tables are created on first start, and while the database has no content the menus use the made-up [`example_content.py`](turbine_troubleshooter/example_content.py). Add codes and parts from **Admin Panel → Add Code / Add Part**. Stop with Ctrl+C.

## Development

```bash
pip install -e ".[dev]"
pre-commit run --all-files
pytest
```

CI fails if any document, image or spreadsheet file is committed, or if the package imports anything from a host application. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to make a change.

## Licence

[MIT](LICENSE). The licence covers the code only; site content supplied by a host is not part of this repository.
