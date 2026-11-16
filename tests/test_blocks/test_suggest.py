import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter.db as db
from turbine_troubleshooter.blocks import suggest
from turbine_troubleshooter.settings import SETTINGS

OWNER = 999
TECH = 5
FILES = Path("/media")

MODULES = {
    "Torque": {
        "menu": {
            "Hub": "Hub text",
            "Charts": {"menu": {"T5": {"text": "", "document": FILES / "pdf/T5.pdf"}}},
        }
    },
    "SLD": {"text": "Single line", "document": [FILES / "pdf/SLD.pdf"]},
    "Note": "Plain",
}


@pytest.fixture(autouse=True)
def content(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", "-100")
    monkeypatch.setattr(SETTINGS, "files_dir", FILES)
    monkeypatch.setattr(
        SETTINGS,
        "content",
        SimpleNamespace(
            MODULES_MAP=deepcopy(MODULES),
            WTG_MAP={"WTA01": {"serial": 1, "ip": "192.0.2.1"}},
            IO_BOARDS={},
        ),
    )
    return SETTINGS.content


@pytest.fixture(autouse=True)
def store(monkeypatch):
    calls = SimpleNamespace(added=[], removed=[], saved=0)

    async def add(s):
        calls.added.append(s)
        return 41

    async def remove(suggestion_id):
        calls.removed.append(suggestion_id)

    async def save():
        calls.saved += 1

    monkeypatch.setattr(suggest, "suggestion_add", add)
    monkeypatch.setattr(suggest, "suggestion_remove", remove)
    monkeypatch.setattr(suggest, "content_save", save)
    return calls


def make_context(is_troubleshooter=True, user_data=None, pending=None):
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        bot=bot,
        user_data=dict(user_data or {}),
        bot_data={
            "is_troubleshooter": is_troubleshooter,
            "pending_suggestions": dict(pending or {}),
        },
    )


def make_query(data, user_id=TECH):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="tech", full_name="Tech"),
        message=SimpleNamespace(message_id=55, chat_id=user_id),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), query


def text_update(user_id=TECH):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
    )


def shown(mock):
    call = mock.await_args
    text = call.kwargs.get("text", call.args[0] if call.args else None)
    markup = call.kwargs["reply_markup"]
    return text, [b.callback_data for row in markup.inline_keyboard for b in row]


def suggestion(**kw):
    return {
        "id": 7,
        "user_id": TECH,
        "name": "@tech",
        "location": ["Torque"],
        "title": "Gearbox filter",
        "body": "Change it *yearly*",
        "file_id": None,
        "file_kind": None,
        **kw,
    }


def test_save_round_trips_existing_content():
    as_json = json.dumps(db.content_to_json(MODULES))

    assert json.loads(as_json)["SLD"]["document"] == ["file:pdf/SLD.pdf"]
    from_db = db.content_from_json(as_json)
    assert from_db == MODULES


@pytest.mark.asyncio
async def test_content_save_writes_every_item(monkeypatch, make_cursor, patch_session):
    monkeypatch.undo()
    monkeypatch.setattr(SETTINGS, "files_dir", FILES)
    monkeypatch.setattr(
        SETTINGS,
        "content",
        SimpleNamespace(MODULES_MAP=deepcopy(MODULES), WTG_MAP={}, IO_BOARDS={}),
    )
    cur = make_cursor()
    patch_session(db, cur)

    await db.content_save()

    saved = {c[1][0]: json.loads(c[1][1]) for c in cur.calls}
    assert set(saved) == {"MODULES_MAP", "WTG_MAP", "IO_BOARDS"}
    assert saved["MODULES_MAP"]["Torque"]["menu"]["Charts"]["menu"]["T5"] == {
        "text": "",
        "document": "file:pdf/T5.pdf",
    }


@pytest.mark.asyncio
async def test_startup_loads_pending_suggestions(make_cursor, patch_session):
    cur = make_cursor()

    async def fetchone():
        sql = cur.calls[-1][0]
        return {"t": sql.split("'")[1]} if sql.startswith("SHOW TABLES") else None

    async def fetchall():
        if cur.calls[-1][0].startswith("SELECT id, user_id, name, location"):
            return [{**suggestion(), "location": '["Torque"]'}]
        return []

    cur.fetchone = AsyncMock(side_effect=fetchone)
    cur.fetchall = AsyncMock(side_effect=fetchall)
    patch_session(db, cur)
    app = SimpleNamespace(bot_data={})

    await db.init_troubleshooter_db(app)

    assert app.bot_data["pending_suggestions"][7]["location"] == ["Torque"]
    assert not any("CREATE TABLE suggestions" in c[0] for c in cur.calls)


@pytest.mark.asyncio
async def test_suggestions_table_created_when_missing(make_cursor, patch_session):
    cur = make_cursor()
    patch_session(db, cur)
    app = SimpleNamespace(bot_data={})

    await db.init_troubleshooter_db(app)

    assert any("CREATE TABLE suggestions" in c[0] for c in cur.calls)
    assert app.bot_data["pending_suggestions"] == {}


def test_menu_paths_lists_every_menu():
    assert suggest.menu_paths() == [(), ("Torque",), ("Torque", "Charts")]


@pytest.mark.parametrize(
    "location,title,problem",
    [
        (["Torque"], "Gearbox filter", None),
        (["Torque"], "hub", "already in that menu"),
        ([], "S.L.D", None),
        ([], "sld", "already in that menu"),
        (["Torque"], "", "between 1 and"),
        (["Torque"], "!!!", "letter or number"),
        (["Gone"], "New", "no longer exists"),
    ],
)
def test_title_problem(location, title, problem):
    result = suggest.title_problem(location, title)
    assert (result is None) if problem is None else (problem in result)


@pytest.mark.asyncio
async def test_flow_text_suggestion_reaches_owner(store):
    context = make_context()
    update, query = make_query("troubleshooter:suggest")
    await suggest.handle_button(update, context)
    _, buttons = shown(query.edit_message_text)
    assert buttons[:3] == [
        "troubleshooter:suggest:where:0",
        "troubleshooter:suggest:where:1",
        "troubleshooter:suggest:where:2",
    ]

    update, query = make_query("troubleshooter:suggest:where:1")
    await suggest.handle_button(update, context)
    assert context.user_data["state"] == "troubleshooter:suggest:title"

    await suggest.handle_text(text_update(), context, "Hub")
    assert "already in that menu" in shown(context.bot.edit_message_text)[0]
    assert context.user_data["state"] == "troubleshooter:suggest:title"

    await suggest.handle_text(text_update(), context, "Gearbox filter")
    assert "PDF or photo" in shown(context.bot.edit_message_text)[0]

    await suggest.handle_text(text_update(), context, "Change it yearly")
    text, buttons = shown(context.bot.edit_message_text)
    assert "Where: Torque" in text
    assert buttons[0] == "troubleshooter:suggest:send"

    update, query = make_query("troubleshooter:suggest:send")
    await suggest.handle_button(update, context)

    assert store.added[0]["title"] == "Gearbox filter"
    assert store.added[0]["location"] == ["Torque"]
    assert 41 in context.bot_data["pending_suggestions"]
    alert = context.bot.send_message.await_args
    assert alert.args[0] == "-100"
    assert "Content Suggestion" in alert.args[1]
    assert "Sent for approval" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_shared_bot_only_asks_for_text():
    context = make_context(
        is_troubleshooter=False,
        user_data={
            "state": "troubleshooter:suggest:title",
            "suggest": {"location": []},
        },
    )

    await suggest.handle_text(text_update(), context, "New note")

    assert "PDF" not in shown(context.bot.edit_message_text)[0]


def file_update(document=None, photo=None, caption=None):
    return SimpleNamespace(
        message=SimpleNamespace(
            document=document, photo=photo, caption=caption, delete=AsyncMock()
        ),
        effective_user=SimpleNamespace(id=TECH),
        effective_chat=SimpleNamespace(id=TECH),
    )


def body_context():
    return make_context(
        user_data={
            "state": "troubleshooter:suggest:body",
            "suggest": {"location": ["Torque"], "title": "Gearbox filter"},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document,photo,kind,problem",
    [
        (
            SimpleNamespace(
                mime_type="application/pdf", file_size=1000, file_id="PDF1"
            ),
            None,
            "document",
            None,
        ),
        (
            None,
            [
                SimpleNamespace(file_size=10, file_id="small"),
                SimpleNamespace(file_size=900, file_id="PHOTO1"),
            ],
            "photo",
            None,
        ),
        (
            SimpleNamespace(mime_type="application/zip", file_size=10, file_id="Z"),
            None,
            None,
            "Only PDFs and photos",
        ),
        (
            SimpleNamespace(
                mime_type="application/pdf", file_size=25 * 1024 * 1024, file_id="B"
            ),
            None,
            None,
            "over 20 MB",
        ),
    ],
)
async def test_file_upload(document, photo, kind, problem):
    context = body_context()

    await suggest.handle_file(file_update(document, photo, "Steps"), context)

    text, _ = shown(context.bot.edit_message_text)
    draft = context.user_data["suggest"]
    if problem:
        assert problem in text
        assert "file_id" not in draft
    else:
        assert draft["file_kind"] == kind
        assert draft["file_id"] in ("PDF1", "PHOTO1")
        assert draft["body"] == "Steps"
        assert "attached" in text


@pytest.mark.asyncio
async def test_file_ignored_outside_suggestion():
    context = make_context()
    update = file_update(SimpleNamespace(mime_type="application/pdf", file_size=1))

    await suggest.handle_file(update, context)

    context.bot.edit_message_text.assert_not_awaited()
    update.message.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "troubleshooter:suggestions",
        "troubleshooter:suggestion:7",
        "troubleshooter:suggestion_ok:7",
        "troubleshooter:suggestion_no:7",
        "troubleshooter:suggestion_file:7",
    ],
)
async def test_review_is_owner_only(store, data):
    context = make_context(pending={7: suggestion()})
    update, query = make_query(data, user_id=TECH)

    await suggest.handle_button(update, context)

    assert "owner" in query.answer.await_args.args[0]
    query.edit_message_text.assert_not_awaited()
    assert store.saved == 0 and store.removed == []


@pytest.mark.asyncio
async def test_card_shows_suggestion_and_file_button():
    context = make_context(pending={7: suggestion(file_id="F", file_kind="document")})
    update, query = make_query("troubleshooter:suggestion:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    text, buttons = shown(query.edit_message_text)
    assert "Gearbox filter" in text and "PDF attached" in text
    assert buttons == [
        "troubleshooter:suggestion_file:7",
        "troubleshooter:suggestion_ok:7",
        "troubleshooter:suggestion_no:7",
        "troubleshooter:suggestions",
    ]


@pytest.mark.asyncio
async def test_approve_text_goes_live(content, store):
    context = make_context(pending={7: suggestion()})
    update, query = make_query("troubleshooter:suggestion_ok:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    assert content.MODULES_MAP["Torque"]["menu"]["Gearbox filter"] == (
        "Change it \\*yearly\\*"
    )
    assert store.saved == 1
    assert store.removed == [7]
    assert context.bot_data["pending_suggestions"] == {}
    assert "has been added" in context.bot.send_message.await_args.args[1]
    assert "Added “Gearbox filter”" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_approve_file_waits_for_upload(content, store):
    context = make_context(pending={7: suggestion(file_id="F", file_kind="document")})
    update, query = make_query("troubleshooter:suggestion_ok:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    entry = content.MODULES_MAP["Torque"]["menu"]["Gearbox filter"]
    assert entry["document"] == FILES / "pdf/Gearbox filter.pdf"
    sent = context.bot.send_document.await_args
    assert sent.args[:2] == (OWNER, "F")
    assert "pdf/Gearbox filter.pdf" in sent.kwargs["caption"]
    assert "once the owner uploads it" in context.bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_approve_avoids_overwriting_an_existing_file(monkeypatch, content):
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "Gearbox filter.jpg")
    context = make_context(pending={7: suggestion(file_id="P", file_kind="photo")})
    update, _ = make_query("troubleshooter:suggestion_ok:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    entry = content.MODULES_MAP["Torque"]["menu"]["Gearbox filter"]
    assert entry["photo"] == FILES / "images/Gearbox filter (7).jpg"


@pytest.mark.asyncio
async def test_failed_save_leaves_content_unchanged(monkeypatch, content, store):
    monkeypatch.setattr(suggest, "content_save", AsyncMock(side_effect=RuntimeError))
    context = make_context(pending={7: suggestion()})
    update, _ = make_query("troubleshooter:suggestion_ok:7", user_id=OWNER)

    with pytest.raises(RuntimeError):
        await suggest.handle_button(update, context)

    assert "Gearbox filter" not in content.MODULES_MAP["Torque"]["menu"]
    assert 7 in context.bot_data["pending_suggestions"]
    assert store.removed == []


@pytest.mark.asyncio
async def test_approve_blocked_when_title_taken_since(content, store):
    content.MODULES_MAP["Torque"]["menu"]["Gearbox Filter"] = "already here"
    context = make_context(pending={7: suggestion()})
    update, query = make_query("troubleshooter:suggestion_ok:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    assert store.saved == 0
    assert "already in that menu" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_reject_tells_user_and_forgets(content, store):
    context = make_context(pending={7: suggestion()})
    update, query = make_query("troubleshooter:suggestion_no:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    assert store.removed == [7] and store.saved == 0
    assert "wasn't added" in context.bot.send_message.await_args.args[1]
    assert "Gearbox filter" not in content.MODULES_MAP["Torque"]["menu"]


@pytest.mark.asyncio
async def test_open_file_sends_it_to_owner():
    context = make_context(pending={7: suggestion(file_id="P", file_kind="photo")})
    update, query = make_query("troubleshooter:suggestion_file:7", user_id=OWNER)

    await suggest.handle_button(update, context)

    assert context.bot.send_photo.await_args.args[:2] == (OWNER, "P")


def draft_context(**draft):
    return make_context(
        user_data={
            "state": "troubleshooter:suggest:body",
            "suggest": {"location": ["Torque"], "title": "Gearbox filter", **draft},
        }
    )


PHOTO = [SimpleNamespace(file_size=900, file_id="PHOTO1")]


@pytest.mark.asyncio
async def test_text_then_photo_keeps_the_text():
    context = draft_context()

    await suggest.handle_text(text_update(), context, "Check the seal")
    _, buttons = shown(context.bot.edit_message_text)
    assert "troubleshooter:suggest:attach" in buttons

    update, query = make_query("troubleshooter:suggest:attach")
    await suggest.handle_button(update, context)
    assert context.user_data["state"] == "troubleshooter:suggest:file"
    assert "Send the PDF or photo" in query.edit_message_text.await_args.args[0]

    await suggest.handle_file(file_update(photo=PHOTO), context)

    draft = context.user_data["suggest"]
    assert draft["body"] == "Check the seal"
    assert draft["file_id"] == "PHOTO1"
    text, buttons = shown(context.bot.edit_message_text)
    assert "Photo attached" in text and "Check the seal" in text
    assert buttons[0] == "troubleshooter:suggest:send"
    assert "troubleshooter:suggest:attach" not in buttons


@pytest.mark.asyncio
async def test_caption_replaces_earlier_text():
    context = draft_context(body="Old", file_id=None, file_kind=None)
    context.user_data["state"] = "troubleshooter:suggest:file"

    await suggest.handle_file(file_update(photo=PHOTO, caption="New"), context)

    assert context.user_data["suggest"]["body"] == "New"


@pytest.mark.asyncio
async def test_photo_then_add_text():
    context = draft_context()
    await suggest.handle_file(file_update(photo=PHOTO), context)
    _, buttons = shown(context.bot.edit_message_text)
    assert "troubleshooter:suggest:text" in buttons

    update, _ = make_query("troubleshooter:suggest:text")
    await suggest.handle_button(update, context)
    assert context.user_data["state"] == "troubleshooter:suggest:text"

    await suggest.handle_text(text_update(), context, "Shows the seal")

    draft = context.user_data["suggest"]
    assert draft["body"] == "Shows the seal" and draft["file_id"] == "PHOTO1"


@pytest.mark.asyncio
async def test_text_too_long_for_a_file_blocks_sending():
    context = draft_context()
    await suggest.handle_text(text_update(), context, "x" * 1500)
    _, buttons = shown(context.bot.edit_message_text)
    assert buttons[0] == "troubleshooter:suggest:send"

    context.user_data["state"] = "troubleshooter:suggest:file"
    await suggest.handle_file(file_update(photo=PHOTO), context)

    text, buttons = shown(context.bot.edit_message_text)
    assert "has to be shorter" in text
    assert "troubleshooter:suggest:send" not in buttons
    assert "troubleshooter:suggest:text" in buttons


@pytest.mark.asyncio
async def test_no_attach_button_where_files_cannot_be_taken():
    context = draft_context()
    context.bot_data["is_troubleshooter"] = False

    await suggest.handle_text(text_update(), context, "Text only")

    _, buttons = shown(context.bot.edit_message_text)
    assert "troubleshooter:suggest:attach" not in buttons


@pytest.mark.asyncio
async def test_add_buttons_after_draft_expired():
    context = make_context()
    update, query = make_query("troubleshooter:suggest:attach")

    await suggest.handle_button(update, context)

    assert "expired" in query.edit_message_text.await_args.args[0]
    assert "state" not in context.user_data


def test_title_taken_by_built_in_io_boards_button():
    assert "already in that menu" in suggest.title_problem([], "IO boards")
    assert suggest.title_problem(["Torque"], "IO Boards") is None


def test_title_taken_by_pending_suggestion_in_same_menu_only():
    pending = {7: suggestion()}

    assert "waiting for approval" in suggest.title_problem(
        ["Torque"], "gearbox FILTER", pending
    )
    assert suggest.title_problem([], "Gearbox filter", pending) is None


@pytest.mark.asyncio
async def test_title_step_rejects_pending_duplicate():
    context = make_context(
        user_data={
            "state": "troubleshooter:suggest:title",
            "suggest": {"location": ["Torque"]},
        },
        pending={7: suggestion()},
    )

    await suggest.handle_text(text_update(), context, "Gearbox filter")

    assert "waiting for approval" in shown(context.bot.edit_message_text)[0]
    assert context.user_data["state"] == "troubleshooter:suggest:title"


@pytest.mark.asyncio
async def test_send_rechecks_title(store):
    context = make_context(
        user_data={
            "suggest": {
                "location": ["Torque"],
                "title": "Gearbox filter",
                "body": "x",
            }
        },
        pending={7: suggestion()},
    )
    update, query = make_query("troubleshooter:suggest:send")

    await suggest.handle_button(update, context)

    assert store.added == []
    assert "waiting for approval" in query.edit_message_text.await_args.args[0]
    context.bot.send_message.assert_not_awaited()
