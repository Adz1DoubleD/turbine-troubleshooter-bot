import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.blocks import admin
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5

NODES = [
    {
        "id": 1,
        "parent_id": None,
        "type": "submenu",
        "title": "Torque",
        "body": None,
        "sort_order": 1,
    },
    {
        "id": 3,
        "parent_id": 1,
        "type": "page",
        "title": "Tower",
        "body": "t",
        "sort_order": 2,
    },
    {
        "id": 2,
        "parent_id": 1,
        "type": "page",
        "title": "Hub",
        "body": "h",
        "sort_order": 1,
    },
    {
        "id": 4,
        "parent_id": None,
        "type": "page",
        "title": "Safety",
        "body": "s",
        "sort_order": 2,
    },
]


@pytest.mark.asyncio
async def test_menus_export_reads_the_rows_in_menu_order(make_cursor, patch_session):
    cur = patch_session(
        ts,
        make_cursor(
            fetchone=[{"t": "menus"}],
            fetchall=[
                sorted(NODES, key=lambda n: (n["sort_order"], n["id"])),
                [
                    {"node_id": 2, "path": "pdf/hub.pdf"},
                    {"node_id": 2, "path": "images/hub.jpg"},
                ],
            ],
        ),
    )

    rows = await ts.db_tables("menus")

    assert [(r["path"], r["files"]) for r in rows] == [
        ("Torque", ""),
        ("Torque › Hub", "pdf/hub.pdf, images/hub.jpg"),
        ("Torque › Tower", ""),
        ("Safety", ""),
    ]
    assert rows[1] == {
        "id": 2,
        "path": "Torque › Hub",
        "type": "page",
        "title": "Hub",
        "body": "h",
        "files": "pdf/hub.pdf, images/hub.jpg",
        "parent_id": 1,
        "position": 1,
    }
    assert not any("FROM `content`" in c[0] for c in cur.calls)


def make(user_id):
    bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock())
    query = SimpleNamespace(
        data="troubleshooter:export:all",
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query, effective_chat=SimpleNamespace(id=user_id)
    )
    context = SimpleNamespace(
        bot=bot, bot_data={"is_troubleshooter": True}, user_data={"is_admin": True}
    )
    return update, context


@pytest.mark.asyncio
async def test_owner_gets_everything_in_one_zip(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    data = {
        "menus": [{"id": 1, "path": "Safety"}],
        "io_boards": [{"board": "io1", "pin": "X1"}, {"board": "io1", "pin": "X2"}],
        "wtgs": [{"name": "WTA01", "serial": "1", "ip": "192.0.2.1"}],
        "codes": None,
        "parts": [{"part_no": "PN1"}],
    }

    async def tables(name):
        return data[name]

    monkeypatch.setattr(admin, "db_tables", tables)
    update, context = make(OWNER)

    await admin.button_export(update, context)

    sent = context.bot.send_document.await_args.kwargs
    assert sent["filename"].startswith("troubleshooter_content_") and sent[
        "filename"
    ].endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(sent["document"].read())) as z:
        assert sorted(z.namelist()) == [
            "io_boards.csv",
            "menus.csv",
            "parts.csv",
            "wtgs.csv",
        ]
        assert z.read("wtgs.csv").decode("utf-8-sig").splitlines() == [
            "name,serial,ip",
            "WTA01,1,192.0.2.1",
        ]
    assert "IO Boards: 2" in sent["caption"] and "Codes: 0" in sent["caption"]
    assert "Photos and PDFs aren't included" in sent["caption"]


@pytest.mark.asyncio
async def test_only_the_owner_exports_everything(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    tables = AsyncMock()
    monkeypatch.setattr(admin, "db_tables", tables)
    update, context = make(ADMIN)

    await admin.button_export(update, context)

    tables.assert_not_awaited()
    context.bot.send_document.assert_not_awaited()
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Only the owner can do that.", show_alert=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("who,shown", [(OWNER, True), (ADMIN, False)])
async def test_everything_button_is_for_the_owner(monkeypatch, who, shown):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    update, context = make(who)

    await admin.button_export_menu(update, context)

    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert ("troubleshooter:export:all" in callbacks) is shown
    assert "📤 Menus" in labels
