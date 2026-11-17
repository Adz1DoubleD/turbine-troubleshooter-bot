from types import SimpleNamespace

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.settings import SETTINGS
from turbine_troubleshooter.tools import find_wtg

ROWS = [
    {"wtg": "WTB01", "serial": "1000101", "ip": "192.0.2.21"},
    {"wtg": "WTA01", "serial": "1000001", "ip": "192.0.2.11"},
    {"wtg": "WTA02", "serial": "SN-2", "ip": None},
]


def tables_db(make_cursor, wtgs=()):
    class Cursor(make_cursor):
        async def _fetchone(self):
            return (
                {"t": 1} if self.calls[-1][0].startswith("SHOW TABLES LIKE") else None
            )

        async def _fetchall(self):
            return list(wtgs) if "FROM wtgs" in self.calls[-1][0] else []

    return Cursor()


@pytest.mark.asyncio
async def test_start_loads_turbines_in_their_saved_order(make_cursor, patch_session):
    cur = patch_session(ts, tables_db(make_cursor, ROWS))

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert list(SETTINGS.content.WTG_MAP) == ["WTB01", "WTA01", "WTA02"]
    assert "SELECT wtg, serial, ip FROM wtgs ORDER BY sort_order, wtg" in [
        c[0] for c in cur.calls
    ]
    assert find_wtg("A1") == ("WTA01", {"serial": "1000001", "ip": "192.0.2.11"})
    assert find_wtg("C9") == ("WTC09", None)


@pytest.mark.asyncio
async def test_wtgs_replace_swaps_the_whole_list(make_cursor, patch_session):
    cur = patch_session(ts, make_cursor())

    await ts.wtgs_replace(
        [
            {"wtg": "WTA02", "serial": "2", "ip": "192.0.2.12"},
            {"wtg": "WTA01", "serial": "1", "ip": None},
        ]
    )

    sql = [c[0] for c in cur.calls]
    assert sql[:2] == ["START TRANSACTION", "DELETE FROM wtgs"]
    assert [c[1] for c in cur.calls if c[0].startswith("INSERT")] == [
        ("WTA02", "2", "192.0.2.12", 1),
        ("WTA01", "1", None, 2),
    ]
    assert sql[-1] == "COMMIT"


@pytest.mark.asyncio
async def test_export_reads_the_table(make_cursor, patch_session):
    rows = [{"name": "WTA01", "serial": "1", "ip": "192.0.2.11"}]
    cur = patch_session(ts, make_cursor(fetchone=[{"t": "wtgs"}], fetchall=[rows]))

    assert await ts.db_tables("wtgs") == rows
    assert "SELECT wtg AS name, serial, ip FROM wtgs ORDER BY sort_order, wtg" in [
        c[0] for c in cur.calls
    ]
