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
| `token` | `TROUBLESHOOTER_BOT_TOKEN` | Bot token from @BotFather (see [Create your Telegram bot](#create-your-telegram-bot)) |
| `owner_id` | `TROUBLESHOOTER_OWNER_ID` | Your Telegram user ID; the owner approves access and admins ([how to find it](#your-telegram-user-id)) |
| `alerts_chat_id` | `TROUBLESHOOTER_ALERTS_CHAT_ID` | Group or channel for new-user, access-request and change notifications. Defaults to the owner's private chat ([setting one up](#an-alerts-group-or-channel)) |
| `timezone` | `TROUBLESHOOTER_TIMEZONE` | Used for edit timestamps and weather. Default `Europe/London` |
| `test_mode` | `TROUBLESHOOTER_TEST_MODE` | `1` while testing: notifications and broadcasts only reach the owner, and errors print a traceback. Off by default |
| `cefas_buoy` | `TROUBLESHOOTER_CEFAS_BUOY` | Cefas WaveNet buoy ID for sea state; enables 🌦 Weather |
| `windquest_location` | `TROUBLESHOOTER_WINDQUEST_LOCATION` | Preferred WindQuest forecast location (falls back to the main location) |
| `windquest_api_key`, `windquest_api_token` | `WINDQUEST_API_KEY`, `WINDQUEST_API_TOKEN` | WindQuest credentials for wind, lightning and tides |
| `files_dir` | — | Folder that `file:` references in the content resolve against |
| `content` | — | Fallback content when the database has none (see below) |
| `noise_filters` | — | Error messages to ignore. Defaults to common network blips |

## Database

MySQL, via `TROUBLESHOOTER_DB_URL`, e.g. `mysql://user:pass@host:3306/db`. It's required: the bot won't start without it, and never falls back to a host's own `JAWSDB_URL`, so it can't end up writing to the host's database. Tables are created on first start: `codes`, `parts`, `users`, one table per IO board, `content`, `menu_nodes` and `attachments` (the menus, below), `settings` and `requests` (access and admin requests waiting for the owner).

`settings` holds the owner's *Notify Users* toggles (`notify_added`, `notify_edited`, `notify_deleted`; on unless a row says `0`), set from **Admin Panel → 🔔 Notify Users**. When one is off, that kind of code or part change is only sent to admins.

## Content

The turbine map and IO boards are loaded from the `content` table: one row per item (`WTG_MAP`, `IO_BOARDS`), stored as JSON text. See [`turbine_troubleshooter/example_content.py`](turbine_troubleshooter/example_content.py) for the shape.

The menus live in `menu_nodes`, one row per button, with photos and PDFs in `attachments`. On the first start with these tables, the bot copies the `MODULES_MAP` row of `content` into them once, keeping the order and nesting, and leaves the `MODULES_MAP` row untouched. Documents and photos are files in `files_dir`; `MODULES_MAP` refers to them as `file:<path relative to files_dir>`.

## Create your Telegram bot

Every copy of the bot needs its own bot account. A token can only be used by one running bot at a time, so two copies sharing one token get "Conflict" errors.

1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Give it a display name, for example `Site Troubleshooter`.
3. Give it a username. It must be unique and end in `bot`, for example `site_troubleshooter_bot`.
4. BotFather replies with a token that looks like `123456789:AAH...`. Put it in `TROUBLESHOOTER_BOT_TOKEN`.

The token is a password: anyone who has it controls the bot. Never commit it or paste it in an issue. If it leaks, send `/revoke` to BotFather to get a new one.

### Your Telegram user ID

The owner is set by user ID, not username. Message [@userinfobot](https://t.me/userinfobot) and it replies with your ID, a number like `123456789`. Put it in `TROUBLESHOOTER_OWNER_ID`.

### An alerts group or channel

Notifications go to the owner's private chat unless you set `TROUBLESHOOTER_ALERTS_CHAT_ID`. To send them to a group or channel instead:

1. Add the bot to the group. For a channel, add it as an admin that can post messages; it can't post in a channel otherwise.
2. Find the chat's ID. With the bot stopped, open `https://api.telegram.org/bot<your token>/getUpdates` in a browser and look for `"chat":{"id":-100...` from adding the bot. If the list is empty, remove the bot and add it again, then reload.
3. Put the ID, including the minus sign, in `TROUBLESHOOTER_ALERTS_CHAT_ID`.

If the host's own bot is also in that group or channel, it receives the troubleshooter's alerts and edits as updates too. Make sure it ignores channel posts and edited channel posts (`~filters.UpdateType.CHANNEL_POSTS` in python-telegram-bot).

## Run it yourself

You need Python 3.12+, a MySQL database and your own test bot ([Create your Telegram bot](#create-your-telegram-bot)). Your copy uses its own bot and database, so it never touches anyone else's.

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
- `TROUBLESHOOTER_BOT_TOKEN`: your test bot's token from [@BotFather](#create-your-telegram-bot).
- `TROUBLESHOOTER_OWNER_ID`: your [Telegram user ID](#your-telegram-user-id).
- `TROUBLESHOOTER_DB_URL`: your MySQL database.

Everything else is optional. Access requests and change notices go to `TROUBLESHOOTER_ALERTS_CHAT_ID`, or to the owner when it isn't set. Then:

```bash
python -m turbine_troubleshooter
```

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
