import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.db.old_content import COPIED_MARKERS, KEEP_TABLES

OLD_BOARDS = {
    "io1": {"name": "IO Board 1"},
    "io2": {"name": "IO Board 2"},
    "gm": {"name": "GM"},
    "io9": {"name": "Never had a table"},
    "menus": {"name": "Not an old board table"},
}


def old_db(make_cursor, tables, markers=COPIED_MARKERS, boards=OLD_BOARDS):
    class Cursor(make_cursor):
        def __init__(self):
            super().__init__()
            self.tables = set(tables)
            self.markers = set(markers)
            self.legacy_column = True

        async def _execute(self, *args):
            await super()._execute(*args)
            sql = args[0]
            if sql.startswith("DROP TABLE IF EXISTS"):
                self.tables.discard(sql.split()[-1].strip("`"))
            elif sql == "ALTER TABLE menus DROP COLUMN legacy_key":
                self.legacy_column = False
            elif sql.startswith("DELETE FROM settings"):
                self.markers -= set(args[1])

        async def _fetchone(self):
            sql = self.calls[-1][0]
            if sql.startswith("SELECT data FROM content"):
                return {"data": json.dumps(boards)} if boards is not None else None
            if sql.startswith("SHOW COLUMNS FROM menus"):
                return {"Field": "legacy_key"} if self.legacy_column else None
            return None

        async def _fetchall(self):
            sql, *params = self.calls[-1]
            if sql == "SHOW TABLES":
                return [{"n": t} for t in sorted(self.tables)]
            if sql.startswith("SELECT name FROM settings WHERE name IN"):
                return [{"name": m} for m in params[0] if m in self.markers]
            return []

    return Cursor()


ALL_OLD = KEEP_TABLES | {"content", "io1", "io2", "gm", "suggestions"}


@pytest.mark.asyncio
async def test_old_content_is_removed_once_everything_was_copied(
    make_cursor, patch_session
):
    cur = patch_session(ts, old_db(make_cursor, ALL_OLD))

    removed = await ts.old_content_remove()

    assert removed == ["io1", "io2", "gm", "suggestions", "content"]
    assert cur.tables == KEEP_TABLES
    assert cur.legacy_column is False
    assert cur.markers == set()
    sql = [c[0] for c in cur.calls]
    assert sql.index("DROP TABLE IF EXISTS content") > sql.index(
        "DROP TABLE IF EXISTS `gm`"
    )
    assert not any("`menus`" in s or "`io9`" in s for s in sql)


@pytest.mark.asyncio
async def test_second_start_has_nothing_to_remove(make_cursor, patch_session):
    cur = patch_session(ts, old_db(make_cursor, KEEP_TABLES, markers=()))

    assert await ts.old_content_remove() is None
    assert not any(c[0].startswith(("DROP", "ALTER", "DELETE")) for c in cur.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", COPIED_MARKERS)
async def test_nothing_is_removed_unless_all_three_copies_were_done(
    make_cursor, patch_session, missing
):
    markers = [m for m in COPIED_MARKERS if m != missing]
    cur = patch_session(ts, old_db(make_cursor, ALL_OLD, markers=markers))

    assert await ts.old_content_remove() is False
    assert cur.tables == ALL_OLD
    assert not any(c[0].startswith(("DROP", "ALTER", "DELETE")) for c in cur.calls)


@pytest.mark.asyncio
async def test_without_board_names_only_content_and_suggestions_go(
    make_cursor, patch_session
):
    cur = patch_session(ts, old_db(make_cursor, ALL_OLD, boards=None))

    assert await ts.old_content_remove() == ["suggestions", "content"]
    assert {"io1", "io2", "gm"} <= cur.tables


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,reported", [(["content"], False), (None, False), (False, True)]
)
async def test_start_reports_old_content_it_could_not_remove(
    monkeypatch, make_cursor, patch_session, result, reported
):
    patch_session(ts, make_cursor())
    monkeypatch.setattr(ts.schema, "old_content_remove", AsyncMock(return_value=result))
    message = MagicMock()
    monkeypatch.setattr(ts.schema.sentry_sdk, "capture_message", message)

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert message.called is reported
    if reported:
        assert "Start version 2.1 once" in message.call_args.args[0]
