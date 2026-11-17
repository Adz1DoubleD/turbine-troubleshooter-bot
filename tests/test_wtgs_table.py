import json
from types import SimpleNamespace

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.settings import SETTINGS
from turbine_troubleshooter.tools import find_wtg

WTG_MAP = {
    "WTB01": {"serial": 1000101, "ip": "192.0.2.21"},
    "WTA01": {"serial": 1000001, "ip": "192.0.2.11"},
    "WTA02": {"serial": "SN-2", "ip": None},
}


def mini_db(make_cursor, marked=()):
    class Cursor(make_cursor):
        def __init__(self):
            super().__init__()
            self.marked = set(marked)
            self.wtgs = []

        async def _execute(self, *args):
            await super()._execute(*args)
            if args[0].startswith("INSERT INTO wtgs"):
                self.wtgs.append(args[1])
            if args[0].startswith("INSERT INTO settings"):
                self.marked.add(args[1][0])

        async def _fetchone(self):
            sql, *params = self.calls[-1]
            if sql.startswith("SELECT value FROM settings"):
                return {"value": 1} if params[0][0] in self.marked else None
            return {"t": 1}

        async def _fetchall(self):
            sql = self.calls[-1][0]
            if sql.startswith("SELECT name, data FROM content"):
                return [
                    {"name": "MODULES_MAP", "data": "{}"},
                    {"name": "WTG_MAP", "data": json.dumps(WTG_MAP)},
                    {"name": "IO_BOARDS", "data": "{}"},
                ]
            if "FROM wtgs" in sql:
                return [
                    {"wtg": w, "serial": s, "ip": i}
                    for w, s, i, _ in sorted(self.wtgs, key=lambda t: t[3])
                ]
            return []

    return Cursor()


@pytest.fixture(autouse=True)
def no_other_copies(monkeypatch):
    async def nothing(_):
        return 0

    monkeypatch.setattr(ts.schema, "menu_migrate", nothing)
    monkeypatch.setattr(ts.schema, "io_boards_migrate", nothing)


@pytest.mark.asyncio
async def test_turbine_lookups_match_the_old_map(
    monkeypatch, make_cursor, patch_session
):
    async def skip(_):
        return 0

    monkeypatch.setattr(ts.schema, "wtgs_migrate", skip)
    patch_session(ts, mini_db(make_cursor))
    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))
    old = {w: find_wtg(w) for w in ("A1", "A2", "B1", "C9")}

    monkeypatch.setattr(ts.schema, "wtgs_migrate", ts.wtgs.wtgs_migrate)
    cur = patch_session(ts, mini_db(make_cursor))
    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))
    new = {w: find_wtg(w) for w in ("A1", "A2", "B1", "C9")}

    assert len(cur.wtgs) == 3
    assert {
        w: (k, v and {f: str(x) if x is not None else None for f, x in v.items()})
        for w, (k, v) in old.items()
    } == new
    assert new["C9"] == ("WTC09", None)


@pytest.mark.asyncio
async def test_copy_keeps_order(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor))

    assert await ts.wtgs_migrate(json.dumps(WTG_MAP)) == 3

    assert cur.wtgs == [
        ("WTB01", "1000101", "192.0.2.21", 1),
        ("WTA01", "1000001", "192.0.2.11", 2),
        ("WTA02", "SN-2", None, 3),
    ]
    sql = [c[0] for c in cur.calls]
    assert sql[-1] == "COMMIT"
    assert sql.index("START TRANSACTION") < sql.index(
        "INSERT INTO settings (name, value) VALUES (%s, 1)"
    )


@pytest.mark.asyncio
async def test_copy_runs_once(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor, marked={ts.WTGS_MIGRATED}))

    assert await ts.wtgs_migrate(json.dumps(WTG_MAP)) == 0

    assert cur.wtgs == []


@pytest.mark.asyncio
async def test_new_database_starts_with_no_turbines(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor))

    assert await ts.wtgs_migrate(None) == 0

    assert cur.wtgs == []
    assert ts.WTGS_MIGRATED in cur.marked


@pytest.mark.asyncio
async def test_failed_copy_is_rolled_back(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor))
    real = cur._execute

    async def fail(*args):
        await real(*args)
        if args[0].startswith("INSERT INTO wtgs") and args[1][0] == "WTA02":
            raise RuntimeError("disk full")

    cur.execute.side_effect = fail

    with pytest.raises(RuntimeError):
        await ts.wtgs_migrate(json.dumps(WTG_MAP))

    assert cur.calls[-1][0] == "ROLLBACK"
    assert ts.WTGS_MIGRATED not in cur.marked


@pytest.mark.asyncio
async def test_failed_copy_keeps_the_old_turbines(
    monkeypatch, make_cursor, patch_session
):
    async def broken(_):
        raise RuntimeError("no space")

    monkeypatch.setattr(ts.schema, "wtgs_migrate", broken)
    patch_session(ts, mini_db(make_cursor))

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert SETTINGS.content.WTG_MAP == WTG_MAP


@pytest.mark.asyncio
async def test_export_reads_the_new_table_once_it_exists(make_cursor, patch_session):
    rows = [{"name": "WTA01", "serial": "1", "ip": "192.0.2.1"}]
    cur = patch_session(ts, make_cursor(fetchone=[{"t": "wtgs"}], fetchall=[rows]))

    assert await ts.db_tables("wtgs") == rows

    assert (
        cur.calls[-1][0]
        == "SELECT wtg AS name, serial, ip FROM wtgs ORDER BY sort_order, wtg"
    )
