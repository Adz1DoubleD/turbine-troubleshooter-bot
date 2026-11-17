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
4. Start each commit message with a type, which decides the next version:
   - `fix: ...` for a bug fix (1.0.0 → 1.0.1)
   - `feat: ...` for something new (1.0.0 → 1.1.0)
   - `feat!: ...` or `fix!: ...` for a change hosts must act on (1.0.0 → 2.0.0)
   - `docs:`, `test:`, `ci:`, `chore:` or `refactor:` for anything that doesn't need a release
5. Open a pull request saying what changed and why. CI runs the same checks and must pass before merging.

Tests mock the database and Telegram, so they need no `.env`, network or MySQL.

## Feature or content?

Before writing a new button, check which kind it is:

- **A feature** makes the bot do something new: a search, an export, a new admin screen. That's code, and a pull request is welcome.
- **Content** shows information: a new menu item, a document, a photo, a torque table, a procedure. Content belongs to whoever hosts the bot: menu text lives in their database and documents in their files folder, never in this repo. Don't open a pull request for it; ask an admin of the bot you use to add it.

If a feature needs example data to demonstrate it, add made-up entries to `example_content.py`.

## Adding a button

1. **The handler** goes in `turbine_troubleshooter/blocks/` (or `blocks/admin/` for admin screens). It edits the current message rather than sending a new one, and gives every screen a 🔙 Back button.
2. **The callback data** starts with `troubleshooter:` and stays under Telegram's 64-byte limit, IDs included.
3. **The route** goes in `handle_button` in `turbine_troubleshooter/__init__.py`. Admin screens go behind `admin and ...`; owner-only actions also check `is_owner()` inside the handler, because admins pass the route.
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

Releases are prepared by [release-please](https://github.com/googleapis/release-please):

1. Every merge to `main` updates a "chore(main): release X.Y.Z" pull request. It works out the next version from the commit types since the last release, bumps `version` in `pyproject.toml` and writes `CHANGELOG.md`.
2. When it's time to release, the maintainer merges that pull request. The workflow can't trigger CI on its own pull requests, so the maintainer merges it past the required check; it only changes the version and changelog.
3. The merge tags `vX.Y.Z`, creates the GitHub release, runs the tests, builds, and waits for the maintainer to approve the `pypi` deployment before uploading to [PyPI](https://pypi.org/project/turbine-troubleshooter-bot/).

If a release changes something users will notice, add a short, plain-language note for its version to `turbine_troubleshooter/whats_new.py` in the same pull request (no code terms; it's broadcast to technicians once the owner approves it).

A version number can only be published once. Pushing a `vX.Y.Z` tag by hand also publishes, as long as it matches `version`. Hosts pin a version, so nothing reaches a live bot until a host moves to the new release.
