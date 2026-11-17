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
| `announce_updates` | `TROUBLESHOOTER_ANNOUNCE_UPDATES` | `0` to stop the owner being offered each release's *What's new* note. On by default ([release notes](#release-notes-for-users)) |
| `files_repo` | `TROUBLESHOOTER_FILES_REPO` | GitHub repo that holds `files_dir`, as `owner/name`. With a token, **💾 Save** commits new photos and PDFs there instead of to `files_dir` ([details](#photos-and-pdfs-on-menu-pages)) |
| `files_repo_branch` | `TROUBLESHOOTER_FILES_REPO_BRANCH` | Branch to save to. Default `main` |
| `files_repo_token` | `TROUBLESHOOTER_FILES_REPO_TOKEN` | Fine-grained GitHub token with *Contents: read and write* on that one repo only |
| `cefas_buoy` | `TROUBLESHOOTER_CEFAS_BUOY` | Cefas WaveNet buoy ID for sea state; enables 🌦 Weather |
| `windquest_location` | `TROUBLESHOOTER_WINDQUEST_LOCATION` | Preferred WindQuest forecast location (falls back to the main location) |
| `windquest_api_key`, `windquest_api_token` | `WINDQUEST_API_KEY`, `WINDQUEST_API_TOKEN` | WindQuest credentials for wind, lightning and tides |
| `files_dir` | `TROUBLESHOOTER_FILES_DIR` (standalone) | Folder the menus' photos and PDFs are kept in, e.g. `pdf/manual.pdf` inside it |
| `noise_filters` | — | Error messages to ignore. Defaults to common network blips |

## Database

MySQL, via `TROUBLESHOOTER_DB_URL`, e.g. `mysql://user:pass@host:3306/db`. It's required: the bot won't start without it, and never falls back to a host's own `JAWSDB_URL`, so it can't end up writing to the host's database. Tables are created on first start: `codes`, `parts`, `users`, `content`, `menus` and `attachments` (the menus, below), `io_boards` (every IO board pin-out, below), `wtgs` (turbine serials and IPs, below), `settings`, `requests` (access and admin requests waiting for the owner) and `delete_requests` (deletes by admins waiting for the owner).

`settings` holds the owner's *Notify Users* toggles (`notify_added`, `notify_edited`, `notify_deleted`; on unless a row says `0`), set from **Admin Panel → 🔔 Notify Users**. When one is off, that kind of code or part change is only sent to admins.

### Photos and PDFs on menu pages

In the troubleshooter bot itself, admins can send a PDF or photo (up to 20 MB) when adding a page, or attach one from **✏️ Edit → 📎 File**. Text sent with it becomes its caption, so the page text is limited to Telegram's 1024-character caption. Only the owner can replace or remove a file. A host showing the menus through `share_with` can't take files, because a Telegram file can only be resent by the bot that received it.

A new file works in the troubleshooter bot straight away. The bot also sends it to the owner with the path to save it as in `files_dir` (for example `pdf/manual.pdf`), and lists it under **Admin Panel → 📎 Pending Files** until it's there. Hosts show files from `files_dir`, so until it's saved a host shows "This document isn't available right now". On each start the bot marks pending files it finds in `files_dir` as saved.

The owner can tap **💾 Save** on that message, or in Pending Files, instead of saving it by hand. Without repo settings it saves the file straight into `files_dir`, which is all a bot on an ordinary server needs. On hosts that reset their disk on each restart, such as Heroku, a file saved that way only lasts until the next restart; the bot then notices it's gone and puts it back in Pending Files.

For those hosts, if `files_dir` is deployed from a GitHub repo, set `TROUBLESHOOTER_FILES_REPO` and `TROUBLESHOOTER_FILES_REPO_TOKEN` and the button becomes **💾 Save to Repo**: it commits the file to the same place in the repo, worked out from where `files_dir` sits under the folder the bot runs from (for a bot started from the top of its repo, `app/media` stays `app/media`), so it's in `files_dir` after the host's next deploy. Use a fine-grained token limited to that one repo with *Contents: read and write*; keep it in the host's environment, never in a file. If GitHub refuses (wrong token, missing folder, a file with that name already there), the owner is told why and the file stays pending.

## Who can change what

The same rules cover fault codes, spare parts and menu items:

| | Owner | Admin | Approved user |
|---|---|---|---|
| View | ✅ | ✅ | ✅ |
| Add | ✅ | ✅ Live at once | ❌ |
| Edit | ✅ | ✅ Live at once; the owner gets the old text with **↩️ Undo** | ❌ |
| Delete | ✅ | Asks the owner, who approves or keeps it from the message or **Admin Panel → 📥 Requests** (which also lists access and admin requests) | ❌ |

Undo only works while the item still has the text the admin saved; if it's been changed again since, the bot says so. Edits made before this version can't be undone, because their old text wasn't kept.

## Content

Turbines live in `wtgs`, one row per turbine with its serial and IP, used by **🔢 WTG Info**. On the first start with this table, the bot copies the `WTG_MAP` row of `content` into it once and leaves that row untouched. On a new database there's nothing to copy, so there are no turbines.

IO board pin-outs live in `io_boards`, one row per pin with its board's ID, name and CAN node, in the order they're shown. On the first start with this table, the bot copies the `IO_BOARDS` row of `content` and the older one-table-per-board tables into it once, and leaves those untouched. On a new database there's nothing to copy, so there are no boards. The **IO Boards** and **🔢 WTG Info** buttons only appear once there's at least one board or turbine.

### Adding turbines and IO boards

Turbines and IO boards aren't edited from the menus. The owner keeps them up to date with a CSV file: **Admin Panel → 📥 Import** in the troubleshooter bot, then **🔢 Turbines** or **📋 IO Boards**. To start from what's there now, use **📤 Export**, edit the file in a spreadsheet, and send it back, saved as *CSV UTF-8*. The bot checks every row first and lists any problems with their row numbers, then shows how many are new, changed and removed before you tap **✅ Import**. An import replaces the whole list, so anything not in the file is removed.

**Turbines** (`wtgs`):

| Column | Meaning |
|---|---|
| `name` | The turbine: `TROUBLESHOOTER_WTG_PREFIX`, a row letter and a two-digit number, e.g. `WTA05`. Technicians look it up as `A5` |
| `serial` | Serial number |
| `ip` | IP address |

```csv
name,serial,ip
WTA01,1000001,192.0.2.11
WTA02,1000002,192.0.2.12
WTB01,1000101,192.0.2.21
```

**IO boards** (`io_boards`), one row per pin, in the order they're shown:

| Column | Meaning |
|---|---|
| `board` | The board's short ID, used in its button: letters, numbers or `_`, e.g. `io1` |
| `board_name` | Name on the board's button and screen |
| `can_node` | Optional CAN node, shown under the board's name |
| `section` | Optional heading the pin is grouped under. Leave it blank on every pin for a board without headings; on a board that has some, blank ones go under **General** |
| `pin` | Pin or terminal label, e.g. `X1:1` |
| `description` | Optional: what's on that pin |

Every row for a board must have the same `board_name` and `can_node`.

```csv
board,board_name,can_node,section,pin,description
io1,IO Board 1,Node 1,Inputs,X1:1,Example signal
io1,IO Board 1,Node 1,Inputs,X1:2,
io1,IO Board 1,Node 1,Outputs,X2:1,Example relay
```

Exports also have `id` and `position` columns; the import ignores them and uses the order of the rows.

The menus live in `menus`, one row per button, with photos and PDFs in `attachments`. On the first start with these tables, the bot copies the `MODULES_MAP` row of `content` into them once, keeping the order and nesting, and leaves the `MODULES_MAP` row untouched. Documents and photos are files in `files_dir`; `MODULES_MAP` refers to them as `file:<path relative to files_dir>`. On a new database there's nothing to copy, so the menus start empty.

Admins add menu items from **Admin Panel → 📝 Add Content**: pick where it goes, then a page (text) or a submenu (more buttons), a title and the text. The bot shows a preview before saving, and sends the text back if Telegram can't show its formatting. Opening a menu item as an admin shows **✏️ Edit** and **🗑 Delete**, and a submenu also shows **➕ Add Here**. A submenu can only be deleted once it's empty. Titles are up to 60 characters, can't contain `*`, `_`, `` ` `` or `[`, and must differ from the others in the same menu.

### Backups

Content lives only in the database, so keep a copy: **Admin Panel → 📤 Export → 📦 Everything (ZIP)** (owner only) sends one ZIP with a CSV each for menus, IO boards, turbines, codes and parts. The turbine and IO board files are in the import format. Photos and PDFs aren't in it; they're the files in `files_dir`, listed in `menus.csv`.

## Release notes for users

A release can come with a short, plain-language *What's new* note in [`whats_new.py`](turbine_troubleshooter/whats_new.py). The first time the bot starts on that version, it sends the owner the note with **📢 Send to Everyone** and **❌ Skip**; nothing reaches users until the owner taps Send, and it can only be sent once. The bot doesn't offer it in test mode, or when it has no approved users yet.

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

Open your test bot in Telegram and send `/start`. As the owner you get the admin panel. Tables are created on first start, and a new database starts empty: no menus, IO boards or turbines. Add codes, parts and menu items from **Admin Panel → Add Code / Add Part / Add Content**. Stop with Ctrl+C.

## Development

```bash
pip install -e ".[dev]"
pre-commit run --all-files
pytest
```

CI fails if any document, image or spreadsheet file is committed, or if the package imports anything from a host application. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to make a change.

## Licence

[MIT](LICENSE). The licence covers the code only; site content supplied by a host is not part of this repository.
