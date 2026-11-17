import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.db as ts
from turbine_troubleshooter.blocks.admin import content, files
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5


def menu():
    return {
        "nodes": [
            {
                "id": 3,
                "parent_id": None,
                "type": "page",
                "title": "Safety",
                "body": "Be safe",
                "sort_order": 1,
                "edits": [],
            },
            {
                "id": 4,
                "parent_id": None,
                "type": "page",
                "title": "Map",
                "body": "The map",
                "sort_order": 2,
                "edits": [],
            },
        ],
        "attachments": [
            {
                "id": 8,
                "node_id": 4,
                "type": "photo",
                "path": "images/map.jpg",
                "file_id": "OLD",
                "file_unique_id": "U-OLD",
                "status": "saved",
            },
        ],
    }


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "menu", menu())
    monkeypatch.setattr(SETTINGS, "files_dir", tmp_path)


@pytest.fixture
def db(monkeypatch):
    m = SimpleNamespace(added=[], files=[], removed=[], notes=[])

    async def add(parent_id, kind, title, body, user_id):
        m.added.append((parent_id, kind, title, body, user_id))
        return {
            "id": 50,
            "parent_id": parent_id,
            "type": kind,
            "title": title,
            "body": body,
            "sort_order": 9,
            "edits": [],
        }

    async def attachment_add(node_id, kind, file_id, unique_id, path, user_id):
        m.files.append((node_id, kind, file_id, unique_id, path, user_id))
        return {
            "id": 70,
            "node_id": node_id,
            "type": kind,
            "file_id": file_id,
            "file_unique_id": unique_id,
            "path": path,
            "status": "pending",
        }

    async def remove(node_id):
        m.removed.append(node_id)
        return 1

    async def notify(*args, **kwargs):
        m.notes.append((args, kwargs))

    monkeypatch.setattr(content, "menu_node_add", add)
    monkeypatch.setattr(files, "attachment_add", attachment_add)
    monkeypatch.setattr(files, "attachments_remove", remove)
    for module in (content, files):
        monkeypatch.setattr(module, "send_notification_troubleshooter", notify)
    return m


def make(user_id=ADMIN, troubleshooter=True):
    user = SimpleNamespace(id=user_id, username="ann", full_name="Ann")
    bot = SimpleNamespace(
        edit_message_text=AsyncMock(),
        send_message=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
    )
    context = SimpleNamespace(
        bot=bot,
        bot_data={
            "is_troubleshooter": troubleshooter,
            "troubleshooter_admins": {ADMIN: "ann"},
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
        message=SimpleNamespace(
            text="menu", message_id=3, chat_id=user.id, photo=None, document=None
        ),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=user,
        effective_chat=SimpleNamespace(id=user.id),
    )
    await turbine_troubleshooter.handle_button(update, context)
    return query


async def upload(user, context, kind="pdf", caption=None, unique="U1", size=1000):
    document = SimpleNamespace(
        file_id="F1",
        file_unique_id=unique,
        file_size=size,
        mime_type="application/pdf" if kind == "pdf" else "text/plain",
    )
    photo = [
        SimpleNamespace(file_id="small", file_unique_id="s", file_size=10),
        SimpleNamespace(file_id="F1", file_unique_id=unique, file_size=size),
    ]
    message = SimpleNamespace(
        photo=photo if kind == "photo" else None,
        document=None if kind == "photo" else document,
        caption=caption,
        delete=AsyncMock(),
    )
    update = SimpleNamespace(
        message=message, effective_user=user, effective_chat=SimpleNamespace(id=user.id)
    )
    await turbine_troubleshooter.file_handler(update, context)
    return context.bot.edit_message_text.await_args.kwargs


async def type_in(text, user, context):
    update = SimpleNamespace(
        message=SimpleNamespace(text=text),
        effective_user=user,
        effective_chat=SimpleNamespace(id=user.id),
    )
    await turbine_troubleshooter.handle_text_input(update, context)
    return context.bot.edit_message_text.await_args.kwargs


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


async def new_page(user, context, title="Manual"):
    await press("troubleshooter:menu_add:in:0", user, context)
    await press("troubleshooter:menu_add:type:page", user, context)
    return await type_in(title, user, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("troubleshooter,offered", [(True, True), (False, False)])
async def test_files_are_offered_only_in_the_troubleshooter_bot(
    db, troubleshooter, offered
):
    user, context = make(troubleshooter=troubleshooter)

    prompt = await new_page(user, context)

    assert ("send a PDF or photo" in prompt["text"]) is offered


@pytest.mark.asyncio
async def test_admin_adds_a_page_with_a_pdf(db):
    user, context = make()
    await new_page(user, context)

    preview = await upload(user, context, caption="Read *this*")

    assert (
        preview["text"] == "👀 *Preview*\n\n*Manual*\n\nRead *this*\n\n📎 PDF attached"
    )
    await press("troubleshooter:menu_add:save", user, context)
    assert db.added == [(None, "page", "Manual", "Read *this*", ADMIN)]
    assert db.files == [(50, "document", "F1", "U1", "pdf/manual.pdf", ADMIN)]
    assert SETTINGS.menu["attachments"][-1]["status"] == "pending"
    sent = context.bot.send_document.await_args
    assert sent.args[:2] == (str(OWNER), "F1")
    assert "`pdf/manual.pdf`" in sent.kwargs["caption"]


@pytest.mark.asyncio
async def test_photo_takes_the_largest_size_and_a_free_name(db, tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "manual.jpg").write_bytes(b"x")
    user, context = make()
    await new_page(user, context)

    await upload(user, context, kind="photo")
    await press("troubleshooter:menu_add:save", user, context)

    assert db.files == [(50, "photo", "F1", "U1", "images/manual_2.jpg", ADMIN)]
    assert context.bot.send_photo.await_args.args[:2] == (str(OWNER), "F1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,size,unique,caption,problem",
    [
        ("text", 10, "U1", None, "Only PDFs and photos"),
        ("pdf", 21 * 1024 * 1024, "U1", None, "over 20 MB"),
        ("pdf", 10, "U-OLD", None, "already on Map"),
        ("pdf", 10, "U1", "x" * 1020, "Keep the text to 1014 characters"),
    ],
    ids=["not-pdf", "too-big", "duplicate", "caption-too-long"],
)
async def test_bad_files_are_sent_back(db, kind, size, unique, caption, problem):
    user, context = make()
    await new_page(user, context)

    shown = await upload(
        user, context, kind=kind, size=size, unique=unique, caption=caption
    )

    assert problem in shown["text"]
    assert context.user_data["state"] == "troubleshooter:menu_add:body"


@pytest.mark.asyncio
async def test_admin_attaches_a_file_to_a_page_without_one(db):
    user, context = make()
    query = await press("troubleshooter:menu_edit:file:3", user, context)
    assert buttons(query.edit_message_text.await_args.kwargs["reply_markup"]) == [
        "troubleshooter:menu:3"
    ]

    preview = await upload(user, context)
    assert preview["text"].endswith("Be safe\n\n📎 PDF attached")
    await press("troubleshooter:menu_edit:save", user, context)

    assert db.removed == []
    assert db.files == [(3, "document", "F1", "U1", "pdf/safety.pdf", ADMIN)]
    assert db.notes[0][1]["message"] == "File added"
    assert SETTINGS.menu["nodes"][0]["body"] == "Be safe"


@pytest.mark.asyncio
async def test_only_the_owner_replaces_a_file(db):
    user, context = make(ADMIN)

    query = await press("troubleshooter:menu_edit:file:4", user, context)

    query.answer.assert_awaited_once_with(
        "⚠️ Only the owner can replace or remove a file.", show_alert=True
    )
    assert context.user_data.get("state") is None


@pytest.mark.asyncio
async def test_owner_replaces_a_file(db):
    user, context = make(OWNER)
    query = await press("troubleshooter:menu_edit:file:4", user, context)
    assert buttons(query.edit_message_text.await_args.kwargs["reply_markup"]) == [
        "troubleshooter:menu_file_rm:4",
        "troubleshooter:menu:4",
    ]

    await upload(user, context, kind="photo")
    await press("troubleshooter:menu_edit:save", user, context)

    assert db.removed == [4]
    assert [a["file_id"] for a in SETTINGS.menu["attachments"]] == ["F1"]
    assert db.notes[0][1]["message"] == "File replaced"


@pytest.mark.asyncio
async def test_owner_removes_a_file(db):
    user, context = make(OWNER)

    query = await press("troubleshooter:menu_file_rm:4", user, context)
    assert buttons(query.edit_message_text.await_args.kwargs["reply_markup"]) == [
        "troubleshooter:menu:4",
        "troubleshooter:menu_file_rm:yes:4",
    ]
    await press("troubleshooter:menu_file_rm:yes:4", user, context)

    assert db.removed == [4]
    assert SETTINGS.menu["attachments"] == []
    assert db.notes[0][1]["message"] == "File removed"


@pytest.mark.asyncio
async def test_admins_cannot_remove_files(db):
    user, context = make(ADMIN)

    await press("troubleshooter:menu_file_rm:yes:4", user, context)

    assert db.removed == []
    assert len(SETTINGS.menu["attachments"]) == 1


@pytest.mark.asyncio
async def test_pending_files_list_and_resend(db):
    SETTINGS.menu["attachments"].append(
        {
            "id": 9,
            "node_id": 3,
            "type": "document",
            "path": "pdf/safety.pdf",
            "file_id": "F9",
            "file_unique_id": "U9",
            "status": "pending",
        }
    )
    user, context = make(OWNER)

    query = await press("troubleshooter:menu_files", user, context)
    args = query.edit_message_text.await_args
    assert "Pending Files* (1)" in args.args[0]
    assert "• Safety: `pdf/safety.pdf`" in args.args[0]
    assert buttons(args.kwargs["reply_markup"]) == [
        "troubleshooter:menu_files:send:9",
        "troubleshooter:admin_menu",
    ]

    query = await press("troubleshooter:menu_files:send:9", user, context)
    assert context.bot.send_document.await_args.args[:2] == (str(OWNER), "F9")
    query.answer.assert_awaited_once_with("📤 Sent.")


@pytest.mark.asyncio
@pytest.mark.parametrize("who,shown", [(OWNER, ["📎 Pending Files (1)"]), (ADMIN, [])])
async def test_admin_panel_shows_pending_files_to_the_owner(who, shown):
    from turbine_troubleshooter.blocks import admin

    SETTINGS.menu["attachments"][0]["status"] = "pending"
    user, context = make(who)
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())

    await admin.handle_block(
        SimpleNamespace(
            callback_query=query,
            effective_user=user,
            effective_chat=SimpleNamespace(id=1),
        ),
        context,
    )

    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert [
        b.text for row in markup.inline_keyboard for b in row if "Files" in b.text
    ] == shown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "troubleshooter,on_disk,sent",
    [(True, False, "OLD"), (False, True, "path"), (False, False, None)],
    ids=["own-bot-uses-file-id", "host-uses-the-file", "host-without-the-file"],
)
async def test_which_copy_of_a_file_is_sent(tmp_path, troubleshooter, on_disk, sent):
    if on_disk:
        (tmp_path / "images").mkdir()
        (tmp_path / "images" / "map.jpg").write_bytes(b"x")
    user, context = make(9, troubleshooter)
    context.user_data["is_admin"] = False
    reply_photo = AsyncMock()
    query = SimpleNamespace(
        data="troubleshooter:menu:4",
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(
            text="menu",
            message_id=3,
            chat_id=9,
            reply_photo=reply_photo,
            delete=AsyncMock(),
        ),
    )
    update = SimpleNamespace(
        callback_query=query, effective_user=user, effective_chat=SimpleNamespace(id=9)
    )

    await turbine_troubleshooter.handle_button(update, context)

    if sent is None:
        reply_photo.assert_not_awaited()
        assert "isn't available" in query.edit_message_text.await_args.args[0]
    else:
        photo = reply_photo.await_args.kwargs["photo"]
        assert photo == ("OLD" if sent == "OLD" else Path(tmp_path) / "images/map.jpg")


@pytest.mark.asyncio
async def test_files_from_non_admins_are_ignored(db):
    user, context = make(9)
    context.user_data.update(
        is_admin=False,
        state="troubleshooter:menu_add:body",
        menu_draft={"parent": None, "type": "page", "title": "X"},
    )

    message = SimpleNamespace(
        photo=None,
        document=SimpleNamespace(
            file_id="F", file_unique_id="U", file_size=1, mime_type="application/pdf"
        ),
        caption=None,
        delete=AsyncMock(),
    )
    await turbine_troubleshooter.file_handler(
        SimpleNamespace(
            message=message, effective_user=user, effective_chat=SimpleNamespace(id=9)
        ),
        context,
    )

    message.delete.assert_not_awaited()
    assert "file" not in context.user_data["menu_draft"]


@pytest.mark.asyncio
async def test_start_marks_files_that_are_now_saved(
    monkeypatch, tmp_path, make_cursor, patch_session
):
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "here.pdf").write_bytes(b"x")
    rows = [
        {
            "id": 1,
            "node_id": 3,
            "type": "document",
            "file_id": "F",
            "file_unique_id": "U",
            "path": "pdf/here.pdf",
            "status": "pending",
        },
        {
            "id": 2,
            "node_id": 3,
            "type": "document",
            "file_id": "G",
            "file_unique_id": "V",
            "path": "pdf/missing.pdf",
            "status": "pending",
        },
    ]

    class Cursor(make_cursor):
        async def _fetchone(self):
            return (
                {"value": 1}
                if self.calls[-1][0].startswith("SELECT value FROM settings")
                else {"t": 1}
            )

        async def _fetchall(self):
            sql = self.calls[-1][0]
            if "FROM attachments" in sql:
                return rows
            if "FROM menus" in sql:
                return [
                    {
                        "id": 3,
                        "parent_id": None,
                        "type": "page",
                        "title": "S",
                        "body": "",
                        "sort_order": 1,
                        "edits": None,
                    }
                ]
            return []

    async def nothing(_):
        return 0

    monkeypatch.setattr(ts.schema, "menu_migrate", nothing)
    cur = patch_session(ts, Cursor())

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    update = [c for c in cur.calls if c[0].startswith("UPDATE attachments")]
    assert update == [("UPDATE attachments SET status = 'saved' WHERE id IN (%s)", [1])]
    assert [a["status"] for a in SETTINGS.menu["attachments"]] == ["saved", "pending"]


@pytest.mark.asyncio
async def test_attachment_add_sql(make_cursor, patch_session):
    cur = patch_session(ts, make_cursor())

    saved = await ts.attachment_add(3, "photo", "F", "U", "images/x.jpg", 5)

    sql, params = cur.execute.call_args.args
    assert sql.startswith("INSERT INTO attachments")
    assert params == (3, "photo", "F", "U", "images/x.jpg", 5)
    assert saved["status"] == "pending" and saved["id"] == 7
    assert json.dumps(saved)
