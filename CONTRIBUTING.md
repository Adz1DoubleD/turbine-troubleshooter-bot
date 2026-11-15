# Contributing

Thanks for helping. To get a copy running, follow [Run it yourself](README.md#run-it-yourself) in the README.

## Making a change

1. Create a branch from `main`.
2. Make your change, with tests for anything that changes behaviour.
3. Run both checks before pushing:
   ```bash
   pre-commit run --all-files
   pytest
   ```
4. Open a pull request saying what changed and why. CI runs the same checks and must pass before merging.

Tests mock the database and Telegram, so they need no `.env`, network or MySQL.

## Feature or content?

Before writing a new button, check which kind it is:

- **A feature** makes the bot do something new: a search, an export, a new admin screen. That's code, and a pull request is welcome.
- **Content** shows information: a new menu item, a document, a photo, a torque table, a procedure. That lives in each host's database, not in this repo. Don't open a pull request for it; ask whoever runs your bot to add it.

If a feature needs example data to demonstrate it, add made-up entries to `example_content.py`.

## Adding a button

1. **The handler** goes in `troubleshooter/blocks/` (or `blocks/admin/` for admin screens). It edits the current message rather than sending a new one, and gives every screen a 🔙 Back button.
2. **The callback data** starts with `troubleshooter:` and stays under Telegram's 64-byte limit, IDs included.
3. **The route** goes in `handle_button` in `troubleshooter/__init__.py`. Admin screens go behind `admin and ...`; owner-only actions also check `is_owner()` inside the handler, because admins pass the route.
4. **Typed input**: set `context.user_data["state"]` and `last_msg_id`, then add the state to `handle_text_input`.
5. **Lists that grow** (users, codes, parts, requests) are paged, because Telegram rejects a message with more than about 100 buttons.
6. **Changes that remove access or delete data** ask for confirmation first.
7. **Tests**: add the callback to the routing tests in `tests/test_routing.py` (the admin-only list if it's an admin screen), and test the handler with made-up data.

## Rules for this repo

- **No site content in the repo.** Fault codes, parts, turbine maps, IO board pin-outs, documents and photos live in the database and the host's files folder, never in git. CI rejects documents, images, spreadsheets and data files (`.json`, `.sql`, `.txt`, `.csv`, database files). Use made-up data in tests and in `example_content.py`; tests check that it stays small and uses placeholder names and documentation-only IP addresses.
- **No imports from a host application.** The package must work on its own; a test fails if it imports `bot`, `config`, `services`, `media` or `main`.
- **Errors go to Sentry**, never to a Telegram chat. Only catch an exception where there is a real fallback, and report it there with `sentry_sdk.capture_exception`; otherwise let it reach the error handler.
- **Settings come from `settings.py`.** A new setting gets a default in `SETTINGS`, an environment variable in `ENV_VARS`, a row in the README table and a line in `.env.example`.

## Code style

- Ruff handles linting and formatting (`pre-commit` runs it). Keep `target-version` at `py313`.
- No code comments or docstrings; explain the why in the pull request.
- Keep logic inline where it is used rather than adding small helper functions.
- Files stay under 600 lines (`pre-commit` checks this).

## Releases

The maintainer bumps `version` in `pyproject.toml`, merges, and tags `vX.Y.Z`. Hosts install a tag, so nothing reaches a live bot until a host moves to the new tag.
