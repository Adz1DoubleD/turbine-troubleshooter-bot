from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

import turbine_troubleshooter
from turbine_troubleshooter.blocks.admin import changes, content
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5


def menu():
    return {
        "nodes": [
            {
                "id": 1,
                "parent_id": None,
                "type": "submenu",
                "title": "Torque",
                "body": None,
                "sort_order": 1,
                "edits": [],
            },
            {
                "id": 2,
                "parent_id": 1,
                "type": "page",
                "title": "Hub",
                "body": "hub text",
                "sort_order": 1,
                "edits": [],
            },
            {
                "id": 3,
                "parent_id": None,
                "type": "page",
                "title": "Safety",
                "body": "Be safe",
                "sort_order": 2,
                "edits": [],
            },
            {
                "id": 4,
                "parent_id": None,
                "type": "page",
                "title": "Map",
                "body": "The map",
                "sort_order": 3,
                "edits": [],
            },
        ],
        "attachments": [
            {
                "node_id": 4,
                "type": "photo",
                "path": "img/m.jpg",
                "file_id": None,
                "status": "saved",
            }
        ],
    }


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "menu", menu())
    monkeypatch.setattr(SETTINGS, "files_dir", "media")
    monkeypatch.setattr(
        content, "local_now", lambda: SimpleNamespace(strftime=lambda f: "NOW")
    )


@pytest.fixture
def db(monkeypatch):
    m = SimpleNamespace(added=[], updated=[], deleted=[], notes=[], asked=[])

    async def add(parent_id, kind, title, body, user_id):
        m.added.append((parent_id, kind, title, body, user_id))
        return {
            "id": 50,
            "parent_id": parent_id,
            "type": kind,
            "title": title,
            "body": body,
            "sort_order": 9,
            "created_by": user_id,
            "edits": [],
        }

    async def update(*args):
        m.updated.append(args)
        return True

    async def delete(node_id):
        m.deleted.append(node_id)
        return True

    async def notify(*args, **kwargs):
        m.notes.append((args, kwargs))

    async def ask(update, context, kind, target, label):
        m.asked.append((kind, target, label))
        return "🗑 Sent to the owner to approve."

    for module in (content, changes):
        monkeypatch.setattr(module, "send_notification_troubleshooter", notify)
        monkeypatch.setattr(module, "menu_node_delete", delete)
        monkeypatch.setattr(module, "menu_node_update", update)
    monkeypatch.setattr(content, "menu_node_add", add)
    monkeypatch.setattr(content, "ask_owner_to_delete", ask)
    return m


def make(user_id=ADMIN, user_data=None):
    user = SimpleNamespace(id=user_id, username="ann", full_name="Ann")
    bot = SimpleNamespace(
        edit_message_text=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
    )
    context = SimpleNamespace(
        bot=bot,
        bot_data={"is_troubleshooter": True},
        user_data={"is_admin": True, **(user_data or {})},
    )
    return user, context


async def press(data, user, context, text="menu"):
    query = SimpleNamespace(
        data=data,
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(text=text, message_id=3, chat_id=user.id),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=user,
        effective_chat=SimpleNamespace(id=user.id),
    )
    await turbine_troubleshooter.handle_button(update, context)
    return query


async def type_in(text, user, context):
    update = SimpleNamespace(
        message=SimpleNamespace(text=text),
        effective_user=user,
        effective_chat=SimpleNamespace(id=user.id),
    )
    await turbine_troubleshooter.handle_text_input(update, context)
    return context.bot.edit_message_text.await_args.kwargs


def shown(query):
    args = query.edit_message_text.await_args
    markup = args.kwargs["reply_markup"]
    text = args.args[0] if args.args else args.kwargs["text"]
    return text, [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_admin_adds_a_page_inside_a_submenu(db):
    user, context = make()

    text, buttons = shown(await press("troubleshooter:menu_add", user, context))
    assert "Where should it go?" in text
    assert buttons == [
        "troubleshooter:menu_add:in:0",
        "troubleshooter:menu_add:in:1",
        "troubleshooter:admin_menu",
    ]

    text, _ = shown(await press("troubleshooter:menu_add:in:1", user, context))
    assert "Torque" in text
    await press("troubleshooter:menu_add:type:page", user, context)
    assert context.user_data["state"] == "troubleshooter:menu_add:title"

    await type_in("Blade bolts", user, context)
    assert context.user_data["state"] == "troubleshooter:menu_add:body"
    preview = await type_in("Torque to *500 Nm*", user, context)
    assert preview["text"] == "👀 *Preview*\n\n*Blade bolts*\n\nTorque to *500 Nm*"
    assert preview["parse_mode"] == "Markdown"
    assert context.user_data["state"] is None

    text, buttons = shown(await press("troubleshooter:menu_add:save", user, context))
    assert db.added == [(1, "page", "Blade bolts", "Torque to *500 Nm*", ADMIN)]
    assert SETTINGS.menu["nodes"][-1]["id"] == 50
    assert db.notes[0][0][1:] == ("menu_added", "Torque › Blade bolts")
    assert buttons == ["troubleshooter:menu:50", "troubleshooter:admin_menu"]
    assert "menu_draft" not in context.user_data


@pytest.mark.asyncio
async def test_admin_adds_a_submenu_to_the_main_menu(db):
    user, context = make()
    await press("troubleshooter:menu_add:in:0", user, context)
    await press("troubleshooter:menu_add:type:submenu", user, context)

    preview = await type_in("Procedures", user, context)

    assert preview["text"] == "👀 *Preview*\n\n*Procedures*\n\n📁 Submenu"
    await press("troubleshooter:menu_add:save", user, context)
    assert db.added == [(None, "submenu", "Procedures", None, ADMIN)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parent,title,problem",
    [
        ("0", "x" * 61, "between 1 and 60"),
        ("0", "Bad_title", "can't contain"),
        ("0", "safety", "already in that menu"),
        ("0", "IO Boards", "already in that menu"),
        ("1", "HUB", "already in that menu"),
    ],
)
async def test_bad_titles_are_refused(db, parent, title, problem):
    user, context = make()
    await press(f"troubleshooter:menu_add:in:{parent}", user, context)
    await press("troubleshooter:menu_add:type:submenu", user, context)

    shown_text = (await type_in(title, user, context))["text"]

    assert problem in shown_text
    assert context.user_data["state"] == "troubleshooter:menu_add:title"


@pytest.mark.asyncio
async def test_same_title_is_fine_in_another_menu(db):
    user, context = make()
    await press("troubleshooter:menu_add:in:1", user, context)
    await press("troubleshooter:menu_add:type:submenu", user, context)

    preview = await type_in("Safety", user, context)

    assert "Preview" in preview["text"]


@pytest.mark.asyncio
async def test_text_telegram_cannot_show_is_sent_back(db):
    user, context = make()
    await press("troubleshooter:menu_add:in:0", user, context)
    await press("troubleshooter:menu_add:type:page", user, context)
    await type_in("Notes", user, context)
    context.bot.edit_message_text.side_effect = [
        BadRequest("Can't parse entities"),
        None,
    ]

    shown_text = (await type_in("broken *bold", user, context))["text"]

    assert "can't show that formatting" in shown_text
    assert context.user_data["state"] == "troubleshooter:menu_add:body"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,undo", [(ADMIN, "troubleshooter:undo:menu:3:0"), (OWNER, None)]
)
async def test_editing_a_page_text(db, who, undo):
    user, context = make(who)
    text, buttons = shown(await press("troubleshooter:menu_edit:3", user, context))
    assert buttons == [
        "troubleshooter:menu_edit:title:3",
        "troubleshooter:menu_edit:body:3",
        "troubleshooter:menu:3",
    ]

    text, _ = shown(await press("troubleshooter:menu_edit:body:3", user, context))
    assert "Be safe" in text
    preview = await type_in("Be very safe", user, context)
    assert preview["text"] == "👀 *Preview*\n\n*Safety*\n\nBe very safe"

    await press("troubleshooter:menu_edit:save", user, context)

    node = SETTINGS.menu["nodes"][2]
    assert node["body"] == "Be very safe"
    assert node["edits"] == [
        {"by": "@ann", "at": "NOW", "changes": {"body": ["Be safe", "Be very safe"]}}
    ]
    assert db.updated == [(3, "body", "Be very safe", who, "@ann", "NOW", "Be safe")]
    assert db.notes[0][1]["undo"] == undo
    assert db.notes[0][1]["was"] == "Be safe"


@pytest.mark.asyncio
async def test_submenus_only_offer_a_new_title(db):
    user, context = make()

    _, buttons = shown(await press("troubleshooter:menu_edit:1", user, context))

    assert buttons == ["troubleshooter:menu_edit:title:1", "troubleshooter:menu:1"]


@pytest.mark.asyncio
async def test_text_with_a_photo_is_kept_to_caption_length(db):
    user, context = make()
    await press("troubleshooter:menu_edit:body:4", user, context)

    shown_text = (await type_in("x" * 1020, user, context))["text"]

    assert "Keep the text to 1017 characters" in shown_text


@pytest.mark.asyncio
async def test_owner_deletes_a_page(db):
    user, context = make(OWNER)

    text, buttons = shown(await press("troubleshooter:menu_del:4", user, context))
    assert "Delete Map" in text
    assert buttons == ["troubleshooter:menu:4", "troubleshooter:menu_del:yes:4"]
    text, buttons = shown(await press("troubleshooter:menu_del:yes:4", user, context))

    assert db.deleted == [4]
    assert [n["id"] for n in SETTINGS.menu["nodes"]] == [1, 2, 3]
    assert SETTINGS.menu["attachments"] == []
    assert db.notes[0][0][1:] == ("menu_deleted", "Map")
    assert buttons == ["troubleshooter:home"]


@pytest.mark.asyncio
async def test_admin_delete_asks_the_owner(db):
    user, context = make(ADMIN)

    text, _ = shown(await press("troubleshooter:menu_del:2", user, context))
    assert "The owner has to approve it" in text
    text, _ = shown(await press("troubleshooter:menu_del:yes:2", user, context))

    assert db.deleted == []
    assert db.asked == [("menu", 2, "Torque › Hub")]
    assert "Sent to the owner" in text


@pytest.mark.asyncio
async def test_a_submenu_with_items_cannot_be_deleted(db):
    user, context = make(OWNER)

    query = await press("troubleshooter:menu_del:yes:1", user, context)

    query.answer.assert_awaited_once_with(
        "⚠️ That submenu has items in it. Delete them first.", show_alert=True
    )
    assert db.deleted == []


@pytest.mark.asyncio
async def test_nothing_can_change_before_the_copy(db, monkeypatch):
    monkeypatch.setattr(SETTINGS, "menu", None)
    user, context = make(OWNER)

    query = await press("troubleshooter:menu_add", user, context)

    assert "copied to the menu tables" in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_screens_show_admin_buttons_only_to_admins(db):
    user, context = make(ADMIN)
    _, page = shown(await press("troubleshooter:menu:3", user, context))
    _, sub = shown(await press("troubleshooter:menu:1", user, context))
    viewer, plain = make(9, {"is_admin": False})
    _, plain_page = shown(await press("troubleshooter:menu:3", viewer, plain))

    assert page == [
        "troubleshooter:menu_edit:3",
        "troubleshooter:menu_del:3",
        "troubleshooter:home",
    ]
    assert sub == [
        "troubleshooter:menu:2",
        "troubleshooter:menu_add:in:1",
        "troubleshooter:menu_edit:1",
        "troubleshooter:menu_del:1",
        "troubleshooter:home",
    ]
    assert plain_page == ["troubleshooter:home"]


@pytest.mark.asyncio
async def test_an_empty_submenu_still_opens(db):
    SETTINGS.menu["nodes"].append(
        {
            "id": 9,
            "parent_id": None,
            "type": "submenu",
            "title": "New",
            "body": None,
            "sort_order": 4,
            "edits": [],
        }
    )
    viewer, context = make(9, {"is_admin": False})

    text, buttons = shown(await press("troubleshooter:menu:9", viewer, context))

    assert text == "*New*\n\nNothing here yet."
    assert buttons == ["troubleshooter:home"]


@pytest.mark.asyncio
async def test_non_admins_cannot_use_the_admin_buttons(db):
    viewer, context = make(9, {"is_admin": False})

    query = await press("troubleshooter:menu_del:yes:3", viewer, context)

    assert db.deleted == [] and db.asked == []
    assert "out of date" in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_undoes_a_menu_edit(db):
    SETTINGS.menu["nodes"][2].update(
        body="Be very safe",
        edits=[
            {"by": "@ann", "at": "x", "changes": {"body": ["Be safe", "Be very safe"]}}
        ],
    )
    user, context = make(OWNER)

    query = await press("troubleshooter:undo:menu:3:0", user, context)

    assert SETTINGS.menu["nodes"][2]["body"] == "Be safe"
    assert db.updated[0][:3] == (3, "body", "Be safe")
    query.answer.assert_awaited_once_with("↩️ Undone.", show_alert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,deleted", [("3", [3]), ("1", [])])
async def test_owner_approves_a_menu_delete(db, monkeypatch, target, deleted):
    monkeypatch.setattr(changes, "delete_request_remove", AsyncMock())
    told = AsyncMock()
    monkeypatch.setattr(changes, "tell_user", told)
    user, context = make(OWNER)
    context.bot_data["pending_delete_requests"] = {
        7: {
            "id": 7,
            "kind": "menu",
            "target": target,
            "label": "X",
            "user_id": ADMIN,
            "name": "@ann",
        }
    }

    await press("troubleshooter:delreq:yes:7", user, context)

    assert db.deleted == deleted
    assert ("wasn't deleted" in told.await_args.args[2]) is (not deleted)


@pytest.mark.asyncio
async def test_admin_panel_has_add_content():
    from turbine_troubleshooter.blocks import admin

    user, context = make(ADMIN)
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(
        callback_query=query, effective_user=user, effective_chat=SimpleNamespace(id=5)
    )

    await admin.handle_block(update, context)

    _, buttons = shown(query)
    assert "troubleshooter:menu_add" in buttons
