import json
from types import SimpleNamespace

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.settings import SETTINGS

BOARDS = {
    "io2": {"name": "IO Board 2", "can": "Node 2"},
    "io1": {"name": "IO Board 1", "can": ""},
    "gone": {"name": "No Table", "can": ""},
}
TABLES = {
    "io1": [
        {"id": 1, "section": "Inputs", "connector": "X1:1", "tdi_text": "Signal A"},
        {"id": 2, "section": "Outputs", "connector": "X2:1", "tdi_text": None},
        {"id": 3, "section": "Inputs", "connector": "X1:2", "tdi_text": "nan"},
    ],
    "io2": [{"id": 1, "section": "Power", "connector": "P1", "tdi_text": "24V"}],
}
COLUMNS = (
    "board_key",
    "board_name",
    "can_node",
    "section",
    "connector",
    "tdi_text",
    "sort_order",
)


def mini_db(make_cursor, marked=(), tables=TABLES):
    class Cursor(make_cursor):
        def __init__(self):
            super().__init__()
            self.marked = set(marked)
            self.io_rows = []

        async def _execute(self, *args):
            await super()._execute(*args)
            sql = args[0]
            if sql.startswith("INSERT INTO io_boards"):
                self.io_rows.append(dict(zip(COLUMNS, args[1])))
            if sql.startswith("INSERT INTO settings"):
                self.marked.add(args[1][0])

        async def _fetchone(self):
            sql, *params = self.calls[-1]
            if sql.startswith("SELECT value FROM settings"):
                return {"value": 1} if params[0][0] in self.marked else None
            if sql == "SHOW TABLES LIKE %s":
                return {"t": 1} if params[0][0] in tables else None
            return {"t": 1}

        async def _fetchall(self):
            sql = self.calls[-1][0]
            if sql.startswith("SELECT name, data FROM content"):
                return [
                    {"name": "MODULES_MAP", "data": "{}"},
                    {"name": "WTG_MAP", "data": "{}"},
                    {"name": "IO_BOARDS", "data": json.dumps(BOARDS)},
                ]
            for key, rows in tables.items():
                if f"FROM `{key}`" in sql:
                    return [{k: v for k, v in r.items() if k != "id"} for r in rows]
            if "FROM io_boards" in sql:
                return sorted(
                    self.io_rows, key=lambda r: (r["board_key"], r["sort_order"])
                )
            return []

    return Cursor()


@pytest.fixture(autouse=True)
def no_menu_copy(monkeypatch):
    async def nothing(_):
        return 0

    monkeypatch.setattr(ts.schema, "menu_migrate", nothing)


@pytest.mark.asyncio
async def test_boards_from_the_table_match_the_old_ones(
    monkeypatch, make_cursor, patch_session
):
    async def skip(_):
        return 0

    monkeypatch.setattr(ts.schema, "io_boards_migrate", skip)
    patch_session(ts, mini_db(make_cursor))
    old = SimpleNamespace(bot_data={})
    await ts.init_troubleshooter_db(old)
    old_boards = SETTINGS.content.IO_BOARDS

    monkeypatch.setattr(ts.schema, "io_boards_migrate", ts.io_boards.io_boards_migrate)
    cur = patch_session(ts, mini_db(make_cursor))
    new = SimpleNamespace(bot_data={})
    await ts.init_troubleshooter_db(new)

    assert len(cur.io_rows) == 4
    assert new.bot_data["io_boards"] == old.bot_data["io_boards"]
    assert {
        k: v for k, v in old_boards.items() if k in TABLES
    } == SETTINGS.content.IO_BOARDS
    assert [p["connector"] for p in new.bot_data["io_boards"]["io1"]] == [
        "X1:1",
        "X2:1",
        "X1:2",
    ]


@pytest.mark.asyncio
async def test_copy_keeps_order_and_skips_boards_without_a_table(
    make_cursor, patch_session
):
    cur = patch_session(ts, mini_db(make_cursor))

    assert await ts.io_boards_migrate(json.dumps(BOARDS)) == 4

    assert [tuple(r.values()) for r in cur.io_rows] == [
        ("io2", "IO Board 2", "Node 2", "Power", "P1", "24V", 1),
        ("io1", "IO Board 1", "", "Inputs", "X1:1", "Signal A", 1),
        ("io1", "IO Board 1", "", "Outputs", "X2:1", None, 2),
        ("io1", "IO Board 1", "", "Inputs", "X1:2", "nan", 3),
    ]
    sql = [c[0] for c in cur.calls]
    assert sql[-1] == "COMMIT"
    assert sql.index("START TRANSACTION") < sql.index(
        "INSERT INTO settings (name, value) VALUES (%s, 1)"
    )
    assert "SELECT section, connector, tdi_text FROM `io1` ORDER BY id" in sql


@pytest.mark.asyncio
async def test_copy_runs_once(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor, marked={ts.IO_BOARDS_MIGRATED}))

    assert await ts.io_boards_migrate(json.dumps(BOARDS)) == 0

    assert cur.io_rows == []
    assert not any(c[0] == "START TRANSACTION" for c in cur.calls)


@pytest.mark.asyncio
async def test_new_database_starts_with_no_boards(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor, tables={}))

    assert await ts.io_boards_migrate(None) == 0

    assert cur.io_rows == []
    assert ts.IO_BOARDS_MIGRATED in cur.marked


@pytest.mark.asyncio
async def test_failed_copy_is_rolled_back(make_cursor, patch_session):
    cur = patch_session(ts, mini_db(make_cursor))
    real = cur._execute

    async def fail(*args):
        await real(*args)
        if args[0].startswith("INSERT INTO io_boards") and args[1][0] == "io1":
            raise RuntimeError("disk full")

    cur.execute.side_effect = fail

    with pytest.raises(RuntimeError):
        await ts.io_boards_migrate(json.dumps(BOARDS))

    assert cur.calls[-1][0] == "ROLLBACK"
    assert ts.IO_BOARDS_MIGRATED not in cur.marked


@pytest.mark.asyncio
async def test_failed_copy_keeps_the_old_boards(
    monkeypatch, make_cursor, patch_session
):
    async def broken(_):
        raise RuntimeError("no space")

    monkeypatch.setattr(ts.schema, "io_boards_migrate", broken)
    patch_session(ts, mini_db(make_cursor))
    app = SimpleNamespace(bot_data={})

    await ts.init_troubleshooter_db(app)

    assert set(app.bot_data["io_boards"]) == {"io1", "io2"}
    assert "gone" in SETTINGS.content.IO_BOARDS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exists,reads",
    [(True, "SELECT * FROM `io_boards`"), (False, "SELECT * FROM `io1`")],
)
async def test_export_reads_the_new_table_once_it_exists(
    make_cursor, patch_session, exists, reads
):
    names = [{"n": "io_boards"}] if exists else [{"n": "io1"}]
    cur = patch_session(ts, make_cursor(fetchall=[names, [{"id": 1}]]))

    await ts.db_tables("io_boards")

    assert reads in [c[0] for c in cur.calls]
