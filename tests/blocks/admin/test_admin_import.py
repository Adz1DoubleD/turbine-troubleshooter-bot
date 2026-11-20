from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.db as ts
from turbine_troubleshooter.blocks.admin import imports
from turbine_troubleshooter.helpers import find_wtg
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5
WTGS = {
    "WTA01": {"serial": "1000001", "ip": "192.0.2.11"},
    "WTA02": {"serial": "1000002", "ip": "192.0.2.12"},
}
BOARDS = {"io1": {"name": "IO Board 1", "can": "Node 1"}}
PINS = {
    "io1": [
        {"section": "Inputs", "pin": "X1:1", "description": "Signal A"},
        {"section": "Inputs", "pin": "X1:2", "description": None},
    ]
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "wtg_prefix", "WT")
    monkeypatch.setattr(
        SETTINGS,
        "content",
        SimpleNamespace(MODULES_MAP={}, WTG_MAP=dict(WTGS), IO_BOARDS=dict(BOARDS)),
    )


@pytest.fixture
def db(monkeypatch):
    m = SimpleNamespace(wtgs=None, pins=None)

    async def wtgs_replace(rows):
        m.wtgs = rows

    async def io_replace(rows):
        m.pins = rows

    monkeypatch.setattr(imports, "wtgs_replace", wtgs_replace)
    monkeypatch.setattr(imports, "io_boards_replace", io_replace)
    return m


def make(user_id=OWNER, troubleshooter=True):
    user = SimpleNamespace(id=user_id, username="own", full_name="Own")
    bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock())
    context = SimpleNamespace(
        bot=bot,
        bot_data={
            "is_troubleshooter": troubleshooter,
            "troubleshooter_admins": {ADMIN: "ann"},
            "io_boards": {k: list(v) for k, v in PINS.items()},
        },
        user_data={"is_admin": True},
    )
    return user, context


async def press(data, user, context):
    query = SimpleNamespace(
        data=data,
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(text="x", message_id=3, chat_id=user.id),
    )
    await turbine_troubleshooter.handle_button(
        SimpleNamespace(callback_query=query, effective_user=user), context
    )
    return query


async def send(csv_text, user, context, name="list.csv", size=None):
    data = ("﻿" + csv_text).encode("utf-8")
    document = SimpleNamespace(
        file_name=name,
        file_size=len(data) if size is None else size,
        get_file=AsyncMock(
            return_value=SimpleNamespace(
                download_as_bytearray=AsyncMock(return_value=bytearray(data))
            )
        ),
    )
    message = SimpleNamespace(
        document=document, photo=None, caption=None, delete=AsyncMock()
    )
    await turbine_troubleshooter._file_handler(
        SimpleNamespace(
            message=message,
            effective_user=user,
            effective_chat=SimpleNamespace(id=user.id),
        ),
        context,
    )
    return context.bot.edit_message_text.await_args.kwargs["text"]


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,troubleshooter,shown",
    [(OWNER, True, True), (ADMIN, True, False), (OWNER, False, False)],
    ids=["owner", "admin", "owner-in-host"],
)
async def test_import_button_is_for_the_owner_in_the_troubleshooter_bot(
    who, troubleshooter, shown
):
    from turbine_troubleshooter.blocks import admin

    user, context = make(who, troubleshooter)
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())

    await admin.handle_block(
        SimpleNamespace(
            callback_query=query,
            effective_user=user,
            effective_chat=SimpleNamespace(id=1),
        ),
        context,
    )

    assert (
        "troubleshooter:import"
        in buttons(query.edit_message_text.await_args.kwargs["reply_markup"])
    ) is shown


@pytest.mark.asyncio
@pytest.mark.parametrize("who,troubleshooter", [(ADMIN, True), (OWNER, False)])
async def test_others_cannot_import(db, who, troubleshooter):
    user, context = make(who, troubleshooter)

    query = await press("troubleshooter:import:save", user, context)

    assert "Only the owner can import" in query.answer.await_args.args[0]
    assert db.wtgs is None


@pytest.mark.asyncio
async def test_turbines_import_with_a_preview(db):
    user, context = make()
    query = await press("troubleshooter:import:wtgs", user, context)
    assert "`name, serial, ip`" in query.edit_message_text.await_args.args[0]

    preview = await send(
        "name,serial,ip\nWTA01,1000001,192.0.2.11\nwta02,9999,192.0.2.99\nWTB01,1000101,192.0.2.21\n",
        user,
        context,
    )

    assert preview.startswith("📥 *3 turbines*")
    assert "1 new, 1 changed, 0 removed." in preview
    assert db.wtgs is None
    await press("troubleshooter:import:save", user, context)
    assert [r["wtg"] for r in db.wtgs] == ["WTA01", "WTA02", "WTB01"]
    assert find_wtg("b1") == ("WTB01", {"serial": "1000101", "ip": "192.0.2.21"})
    assert find_wtg("A2")[1]["serial"] == "9999"


@pytest.mark.asyncio
async def test_removed_turbines_are_called_out(db):
    user, context = make()
    await press("troubleshooter:import:wtgs", user, context)

    preview = await send("name,serial,ip\nWTA01,1000001,192.0.2.11\n", user, context)

    assert "0 new, 0 changed, 1 removed." in preview
    assert "Removed ones are deleted." in preview


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "csv_text,name,size,problem",
    [
        ("name,serial,ip\nA1,1,x\n", "t.csv", None, "Row 2: A1 isn't a turbine name"),
        (
            "name,serial,ip\nWTA01,1,x\nWTA01,2,y\n",
            "t.csv",
            None,
            "Row 3: WTA01 is also on row 2",
        ),
        ("name,ip\nWTA01,x\n", "t.csv", None, "Missing columns: serial"),
        ("name,serial,ip\n", "t.csv", None, "The file has no rows"),
        ("name,serial,ip\nWTA01,1,x\n", "t.xlsx", None, "Send the list as a .csv file"),
        ("name,serial,ip\nWTA01,1,x\n", "t.csv", 2 * 1024 * 1024, "over 1 MB"),
    ],
    ids=["bad-name", "duplicate", "missing-column", "empty", "not-csv", "too-big"],
)
async def test_bad_turbine_files_save_nothing(db, csv_text, name, size, problem):
    user, context = make()
    await press("troubleshooter:import:wtgs", user, context)

    shown = await send(csv_text, user, context, name=name, size=size)

    assert "Nothing was saved" in shown
    assert problem in shown.replace("\\", "")
    assert db.wtgs is None
    assert context.user_data["state"] == "troubleshooter:import:wtgs"
    assert SETTINGS.content.WTG_MAP == WTGS


@pytest.mark.asyncio
async def test_io_boards_import(db):
    user, context = make()
    await press("troubleshooter:import:io_boards", user, context)

    preview = await send(
        "board,board_name,can_node,section,pin,description\n"
        "io1,IO Board 1,Node 1,Inputs,X1:1,Signal A\n"
        "io1,IO Board 1,Node 1,Inputs,X1:2,Signal B\n"
        "IO2,IO Board 2,,Power,P1,\n",
        user,
        context,
    )

    assert preview.startswith("📥 *2 IO boards, 3 pins*")
    assert "1 new, 1 changed, 0 removed." in preview
    await press("troubleshooter:import:save", user, context)
    assert [(p["board"], p["pin"]) for p in db.pins] == [
        ("io1", "X1:1"),
        ("io1", "X1:2"),
        ("io2", "P1"),
    ]
    assert SETTINGS.content.IO_BOARDS == {
        "io1": {"name": "IO Board 1", "can": "Node 1"},
        "io2": {"name": "IO Board 2", "can": ""},
    }
    assert context.bot_data["io_boards"]["io2"] == [
        {"section": "Power", "pin": "P1", "description": None}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row,problem",
    [
        (
            "io1,Other Name,Node 1,Inputs,X1:3,",
            "Row 4: io1 has a different board_name or can_node from row 2",
        ),
        ("io 3,IO Board 3,,Inputs,X1,", "Row 4: board must be letters"),
        (
            "io1,IO Board 1,Node 1,Inputs,,",
            "Row 4: board_name and pin can't be blank",
        ),
    ],
    ids=["inconsistent-board", "bad-key", "blank-connector"],
)
async def test_bad_io_board_files_save_nothing(db, row, problem):
    user, context = make()
    await press("troubleshooter:import:io_boards", user, context)

    shown = await send(
        "board,board_name,can_node,section,pin,description\n"
        "io1,IO Board 1,Node 1,Inputs,X1:1,Signal A\n"
        "io1,IO Board 1,Node 1,Inputs,X1:2,\n" + row + "\n",
        user,
        context,
    )

    assert "Nothing was saved" in shown
    assert problem in shown.replace("\\", "")
    assert db.pins is None


@pytest.mark.asyncio
async def test_cancel_saves_nothing(db):
    user, context = make()
    await press("troubleshooter:import:wtgs", user, context)
    await send("name,serial,ip\nWTB01,1,192.0.2.1\n", user, context)

    query = await press("troubleshooter:import:cancel", user, context)

    assert db.wtgs is None
    assert "import_draft" not in context.user_data
    assert query.edit_message_text.await_args.args[0] == "Nothing was imported."


@pytest.mark.asyncio
async def test_an_exported_file_imports_with_no_changes(db):
    from turbine_troubleshooter.db.export import db_export

    user, context = make()
    wtg_csv = (
        db_export([{"name": w, **v} for w, v in WTGS.items()])
        .getvalue()
        .decode("utf-8-sig")
    )
    io_csv = (
        db_export(
            [
                {
                    "id": i,
                    "board": "io1",
                    "board_name": "IO Board 1",
                    "can_node": "Node 1",
                    **p,
                    "position": i,
                }
                for i, p in enumerate(PINS["io1"], 1)
            ]
        )
        .getvalue()
        .decode("utf-8-sig")
    )

    await press("troubleshooter:import:wtgs", user, context)
    assert "0 new, 0 changed, 0 removed." in await send(wtg_csv, user, context)
    await press("troubleshooter:import:io_boards", user, context)
    assert "0 new, 0 changed, 0 removed." in await send(io_csv, user, context)


@pytest.mark.asyncio
async def test_files_from_anyone_else_are_ignored(db):
    user, context = make(ADMIN)
    context.user_data["state"] = "troubleshooter:import:wtgs"

    message = SimpleNamespace(
        document=None, photo=None, caption=None, delete=AsyncMock()
    )
    await turbine_troubleshooter._file_handler(
        SimpleNamespace(
            message=message, effective_user=user, effective_chat=SimpleNamespace(id=5)
        ),
        context,
    )

    message.delete.assert_not_awaited()
    context.bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replace,table", [(ts.wtgs_replace, "wtgs"), (ts.io_boards_replace, "io_boards")]
)
async def test_replace_is_one_transaction(make_cursor, patch_session, replace, table):
    cur = patch_session(ts, make_cursor())
    rows = (
        [{"wtg": "WTA01", "serial": "1", "ip": None}]
        if table == "wtgs"
        else [
            {
                "board": "io1",
                "board_name": "B",
                "can_node": "",
                "section": "S",
                "pin": "C",
                "description": None,
            }
        ]
        * 2
    )

    await replace(rows)

    sql = [c[0] for c in cur.calls]
    assert sql[0] == "START TRANSACTION"
    assert sql[1] == f"DELETE FROM {table}"
    assert sql[-1] == "COMMIT"
    if table == "io_boards":
        assert [c[1][-1] for c in cur.calls[2:4]] == [1, 2]


@pytest.mark.asyncio
async def test_replace_rolls_back_on_failure(make_cursor, patch_session):
    cur = patch_session(ts, make_cursor())
    real = cur._execute

    async def fail(*args):
        await real(*args)
        if args[0].startswith("INSERT"):
            raise RuntimeError("bad")

    cur.execute.side_effect = fail

    with pytest.raises(RuntimeError):
        await ts.wtgs_replace([{"wtg": "WTA01", "serial": "1", "ip": None}])

    assert cur.calls[-1][0] == "ROLLBACK"


@pytest.mark.asyncio
async def test_io_board_sections_are_optional(db):
    user, context = make()
    await press("troubleshooter:import:io_boards", user, context)

    preview = await send(
        "board,board_name,pin\nio9,Small Board,P1\nio9,Small Board,P2\n", user, context
    )

    assert "Nothing was saved" not in preview
    await press("troubleshooter:import:save", user, context)
    assert [(p["pin"], p["section"]) for p in db.pins] == [("P1", None), ("P2", None)]
