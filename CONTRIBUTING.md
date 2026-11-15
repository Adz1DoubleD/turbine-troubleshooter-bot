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

## Rules for this repo

- **No site content in the repo.** Fault codes, parts, turbine maps, IO board pin-outs, documents and photos live in the database and the host's files folder, never in git. CI rejects PDFs, images and spreadsheets. Use made-up data in tests and in `example_content.py`.
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
