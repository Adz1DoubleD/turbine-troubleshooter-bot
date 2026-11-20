from types import SimpleNamespace

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.settings import SETTINGS

ROWS = [
    {
        "board": "io1",
        "board_name": "IO Board 1",
        "can_node": "Node 1",
        "section": "Inputs",
        "pin": "X1",
        "description": "First",
    },
    {
        "board": "io1",
        "board_name": "IO Board 1",
        "can_node": "Node 1",
        "section": None,
        "pin": "X2",
        "description": "Second",
    },
    {
        "board": "io2",
        "board_name": "IO Board 2",
        "can_node": None,
        "section": None,
        "pin": "Y1",
        "description": None,
    },
]


def tables_db(make_cursor, boards=()):
    class Cursor(make_cursor):
        async def _fetchone(self):
            return (
                {"t": 1} if self.calls[-1][0].startswith("SHOW TABLES LIKE") else None
            )

        async def _fetchall(self):
            return list(boards) if "FROM io_boards" in self.calls[-1][0] else []

    return Cursor()


@pytest.mark.asyncio
async def test_start_loads_boards_and_pins_in_order(make_cursor, patch_session):
    patch_session(ts, tables_db(make_cursor, ROWS))
    app = SimpleNamespace(bot_data={})

    await ts.init_troubleshooter_db(app)

    assert SETTINGS.content.IO_BOARDS == {
        "io1": {"name": "IO Board 1", "can": "Node 1"},
        "io2": {"name": "IO Board 2", "can": ""},
    }
    assert app.bot_data["io_boards"] == {
        "io1": [
            {"section": "Inputs", "pin": "X1", "description": "First"},
            {"section": None, "pin": "X2", "description": "Second"},
        ],
        "io2": [{"section": None, "pin": "Y1", "description": None}],
    }


@pytest.mark.asyncio
async def test_no_rows_means_no_boards(make_cursor, patch_session):
    patch_session(ts, tables_db(make_cursor))
    app = SimpleNamespace(bot_data={})

    await ts.init_troubleshooter_db(app)

    assert SETTINGS.content.IO_BOARDS == {}
    assert app.bot_data["io_boards"] == {}


@pytest.mark.asyncio
async def test_io_boards_replace_numbers_pins_per_board(make_cursor, patch_session):
    cur = patch_session(ts, make_cursor())

    await ts.io_boards_replace([{**r, "can_node": r["can_node"] or ""} for r in ROWS])

    sql = [c[0] for c in cur.calls]
    assert sql[:2] == ["START TRANSACTION", "DELETE FROM io_boards"]
    inserted = [c[1] for c in cur.calls if c[0].startswith("INSERT")]
    assert [(p[0], p[4], p[6]) for p in inserted] == [
        ("io1", "X1", 1),
        ("io1", "X2", 2),
        ("io2", "Y1", 1),
    ]
    assert sql[-1] == "COMMIT"


@pytest.mark.asyncio
async def test_export_reads_the_table(make_cursor, patch_session):
    cur = patch_session(ts, make_cursor(fetchall=[[{"n": "io_boards"}], [{"id": 1}]]))

    assert await ts.db_tables("io_boards") == [{"id": 1}]
    assert "SELECT * FROM `io_boards`" in [c[0] for c in cur.calls]
