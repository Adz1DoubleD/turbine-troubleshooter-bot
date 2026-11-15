from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import troubleshooter.blocks.admin as admin
from troubleshooter.blocks.admin import codes as admin_codes

CODE = {
    "id": 2,
    "code": "14040",
    "advice": "Check the fuse",
    "parts": "Fuse 5A",
    "added_by": "@alice",
    "edits": [],
}
NOW_UTC = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
NOW = datetime(2026, 7, 2, 0, 30)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW_UTC.astimezone(tz) if tz else NOW_UTC.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(admin, "datetime", FrozenDatetime)


@pytest.fixture
def db(monkeypatch):
    m = SimpleNamespace(added=[], deleted=[], notes=[], blocks=[])
    m.add_result = 42
    m.delete_result = True
    m.error = None

    async def fake_add(**kwargs):
        m.added.append(kwargs)
        if m.error:
            raise m.error
        return m.add_result

    async def fake_delete(table, column, value):
        m.deleted.append((table, column, value))
        if m.error:
            raise m.error
        return m.delete_result

    async def fake_notify(*args, **kwargs):
        m.notes.append(args)
        return 0, 0, []

    async def fake_block(update, context, status=None):
        m.blocks.append(status)

    monkeypatch.setattr(admin_codes, "fault_code_add", fake_add)
    monkeypatch.setattr(admin_codes, "delete_entry", fake_delete)
    monkeypatch.setattr(admin_codes, "send_notification_troubleshooter", fake_notify)
    monkeypatch.setattr(admin_codes, "handle_block", fake_block)
    return m


def make_user(username="editor"):
    return SimpleNamespace(id=5, username=username, full_name="Ed Itor")


def make_update(data=None, user=None):
    calls = {"answers": [], "edits": []}

    async def answer(text=None, **kwargs):
        calls["answers"].append(text)

    async def edit_message_text(text=None, **kwargs):
        calls["edits"].append({"text": text, **kwargs})

    user = user or make_user()
    query = SimpleNamespace(
        data=data,
        from_user=user,
        message=SimpleNamespace(message_id=55, chat_id=1),
        answer=answer,
        edit_message_text=edit_message_text,
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=user,
        effective_chat=SimpleNamespace(id=1),
    )
    return update, calls


def make_context(is_admin=True, user_data=None, code_list=None):
    record = {"edits": [], "actions": []}

    async def edit_message_text(**kwargs):
        record["edits"].append(kwargs)

    async def send_chat_action(chat_id, action):
        record["actions"].append(action)

    codes = code_list if code_list is not None else [dict(CODE)]
    context = SimpleNamespace(
        user_data={"is_admin": is_admin, **(user_data or {})},
        bot_data={"codes": {c["code"]: c for c in codes}, "is_troubleshooter": True},
        bot=SimpleNamespace(
            edit_message_text=edit_message_text, send_chat_action=send_chat_action
        ),
    )
    return context, record


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


ADMIN_BUTTONS = [
    "button_code_add",
    "button_code_delete",
    "button_code_delete_confirm",
    "button_code_edit",
    "button_code_edit_field",
    "button_code_edit_save",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ADMIN_BUTTONS)
async def test_buttons_reject_non_admin(db, handler):
    update, calls = make_update("troubleshooter:code_edit:14040")
    context, record = make_context(
        is_admin=False, user_data={"code_edit_buffer": dict(CODE)}
    )

    await getattr(admin_codes, handler)(update, context)

    assert "Unauthorized" in calls["answers"][0]
    assert calls["edits"] == [] and record["edits"] == []
    assert db.added == [] and db.deleted == [] and db.notes == []
    assert "14040" in context.bot_data["codes"]


@pytest.mark.asyncio
async def test_add_button_asks_for_code():
    update, calls = make_update("troubleshooter:code_add")
    context, _ = make_context()

    await admin_codes.button_code_add(update, context)

    assert context.user_data["state"] == "troubleshooter:code_add:code"
    assert context.user_data["last_msg_id"] == 55
    assert "Step 1" in calls["edits"][0]["text"]
    assert callbacks(calls["edits"][0]["reply_markup"]) == ["troubleshooter:admin_menu"]


@pytest.mark.asyncio
async def test_add_flow_saves_and_notifies(db):
    update, _ = make_update()
    context, record = make_context(
        user_data={"state": "troubleshooter:code_add:code", "last_msg_id": 55},
        code_list=[],
    )

    await admin_codes.handle_code_add(
        update, context, "E_1", "troubleshooter:code_add:code"
    )
    assert context.user_data["state"] == "troubleshooter:code_add:advice"
    assert context.user_data["new_entry"] == {"code": "E_1"}
    assert "`E_1`" in record["edits"][-1]["text"]
    assert record["edits"][-1]["message_id"] == 55

    await admin_codes.handle_code_add(
        update, context, "Reset it", "troubleshooter:code_add:advice"
    )
    assert context.user_data["state"] == "troubleshooter:code_add:parts"
    assert "Step 3" in record["edits"][-1]["text"]

    await admin_codes.handle_code_add(
        update, context, "Fuse 5A", "troubleshooter:code_add:parts"
    )

    expected = {
        "code": "E_1",
        "advice": "Reset it",
        "parts": "Fuse 5A",
        "added_by": "@editor",
        "added_at": NOW,
    }
    assert db.added == [expected]
    assert context.bot_data["codes"]["E_1"] == {**expected, "id": 42}
    assert context.user_data["state"] is None
    assert "Success" in db.blocks[0]
    assert db.notes == [
        (update.effective_user, "code_added", "E_1", "Reset it", "Fuse 5A")
    ]


@pytest.mark.asyncio
async def test_add_uses_full_name_without_username(db):
    user = make_user(username=None)
    update, _ = make_update(user=user)
    context, _ = make_context(
        user_data={"new_entry": {"code": "E1", "advice": "a"}}, code_list=[]
    )

    await admin_codes.handle_code_add(
        update, context, "p", "troubleshooter:code_add:parts"
    )

    assert db.added[0]["added_by"] == "Ed Itor"


@pytest.mark.asyncio
async def test_add_db_error_keeps_code_out(db):
    db.error = RuntimeError("offline")
    update, _ = make_update()
    context, _ = make_context(
        user_data={"new_entry": {"code": "E1", "advice": "a"}}, code_list=[]
    )

    with pytest.raises(RuntimeError, match="offline"):
        await admin_codes.handle_code_add(
            update, context, "p", "troubleshooter:code_add:parts"
        )

    assert "E1" not in context.bot_data["codes"]
    assert db.blocks == []
    assert db.notes == []


@pytest.mark.asyncio
async def test_add_existing_code_offers_edit_or_remove(db):
    update, _ = make_update()
    context, record = make_context(
        user_data={"state": "troubleshooter:code_add:code", "last_msg_id": 55}
    )

    await admin_codes.handle_code_add(
        update, context, "14040", "troubleshooter:code_add:code"
    )

    edit = record["edits"][0]
    assert "already exists" in edit["text"]
    assert "Check the fuse" in edit["text"]
    assert callbacks(edit["reply_markup"]) == [
        "troubleshooter:code_edit:14040",
        "troubleshooter:code_confirm_del:14040",
        "back:troubleshooter",
    ]
    assert context.user_data["state"] is None
    assert "new_entry" not in context.user_data
    assert db.added == []


@pytest.mark.asyncio
async def test_add_without_message_id_still_moves_on():
    update, _ = make_update()
    context, record = make_context(code_list=[])

    await admin_codes.handle_code_add(
        update, context, "E1", "troubleshooter:code_add:code"
    )

    assert context.user_data["state"] == "troubleshooter:code_add:advice"
    assert record["edits"] == []


@pytest.mark.asyncio
async def test_delete_confirm_shows_yes_and_no():
    update, calls = make_update("troubleshooter:code_confirm_del:14040")
    context, record = make_context()

    await admin_codes.button_code_delete_confirm(update, context)

    assert record["actions"] == ["typing"]
    assert "`14040`" in calls["edits"][0]["text"]
    assert callbacks(calls["edits"][0]["reply_markup"]) == [
        "back:troubleshooter",
        "troubleshooter:code_delete:14040",
    ]


@pytest.mark.asyncio
async def test_delete_removes_code_and_notifies(db):
    update, _ = make_update("troubleshooter:code_delete:14040")
    context, _ = make_context()

    status = await admin_codes.button_code_delete(update, context)

    assert db.deleted == [("codes", "code", "14040")]
    assert "14040" not in context.bot_data["codes"]
    assert "removed" in status
    assert db.notes == [(update.callback_query.from_user, "code_deleted", "14040")]


@pytest.mark.asyncio
async def test_delete_not_in_db_keeps_code(db):
    db.delete_result = False
    update, _ = make_update("troubleshooter:code_delete:14040")
    context, _ = make_context()

    status = await admin_codes.button_code_delete(update, context)

    assert "was not found" in status
    assert "14040" in context.bot_data["codes"]
    assert db.notes == []


@pytest.mark.asyncio
async def test_delete_db_error_raises_and_keeps_code(db):
    db.error = RuntimeError("offline")
    update, _ = make_update("troubleshooter:code_delete:14040")
    context, _ = make_context()

    with pytest.raises(RuntimeError, match="offline"):
        await admin_codes.button_code_delete(update, context)

    assert "14040" in context.bot_data["codes"]
    assert db.notes == []


@pytest.mark.asyncio
async def test_edit_opens_editor_with_a_copy():
    update, _ = make_update("troubleshooter:code_edit:14040")
    context, record = make_context()

    await admin_codes.button_code_edit(update, context)

    buffer = context.user_data["code_edit_buffer"]
    assert buffer == context.bot_data["codes"]["14040"]
    assert buffer is not context.bot_data["codes"]["14040"]
    assert context.user_data["last_msg_id"] == 55
    edit = record["edits"][0]
    assert "`14040`" in edit["text"] and "Select a field" in edit["text"]
    assert callbacks(edit["reply_markup"]) == [
        "troubleshooter:code_edit_field:advice",
        "troubleshooter:code_edit_field:parts",
        "back:troubleshooter",
        "troubleshooter:code_edit_save",
    ]


@pytest.mark.asyncio
async def test_edit_missing_code():
    update, calls = make_update("troubleshooter:code_edit:99999")
    context, record = make_context()

    await admin_codes.button_code_edit(update, context)

    assert "not found" in calls["answers"][0]
    assert "code_edit_buffer" not in context.user_data
    assert record["edits"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, current", [("advice", "Check the fuse"), ("parts", "Fuse 5A")]
)
async def test_edit_field_asks_for_new_value(field, current):
    update, calls = make_update(f"troubleshooter:code_edit_field:{field}")
    context, _ = make_context(user_data={"code_edit_buffer": dict(CODE)})

    await admin_codes.button_code_edit_field(update, context)

    assert context.user_data["state"] == f"troubleshooter:code_await_edit:{field}"
    assert f"*Current:* {current}" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_editor_after_change_says_field_updated():
    context, record = make_context(user_data={"code_edit_buffer": dict(CODE)})

    await admin_codes.handle_code_edit(context, 1, 55, updated=True)

    assert "Field updated" in record["edits"][0]["text"]


@pytest.mark.asyncio
async def test_editor_without_buffer_does_nothing():
    context, record = make_context()

    await admin_codes.handle_code_edit(context, 1, 55)

    assert record["edits"] == []


@pytest.mark.asyncio
async def test_save_writes_edit_history_and_notifies(db):
    buffer = dict(CODE, advice="New advice", edits=[{"by": "@bob", "at": "x"}])
    update, _ = make_update("troubleshooter:code_edit_save")
    context, _ = make_context(user_data={"code_edit_buffer": buffer})

    status, code = await admin_codes.button_code_edit_save(update, context)

    assert (status, code) == ("✅ *Saved*", "14040")
    sent = db.added[0]
    assert sent["advice"] == "New advice"
    assert sent["edited_by"] == "@editor"
    assert sent["edited_at"] == "2026-07-02 00:30"
    saved = context.bot_data["codes"]["14040"]
    assert saved["advice"] == "New advice"
    assert saved["edits"] == [
        {"by": "@bob", "at": "x"},
        {"by": "@editor", "at": "2026-07-02 00:30"},
    ]
    assert "code_edit_buffer" not in context.user_data
    assert db.notes == [
        (
            update.callback_query.from_user,
            "code_edited",
            "14040",
            "New advice",
            "Fuse 5A",
        )
    ]


@pytest.mark.asyncio
async def test_save_first_edit_starts_history(db):
    buffer = {k: v for k, v in CODE.items() if k != "edits"}
    update, _ = make_update("troubleshooter:code_edit_save", user=make_user(None))
    context, _ = make_context(user_data={"code_edit_buffer": buffer})

    await admin_codes.button_code_edit_save(update, context)

    assert context.bot_data["codes"]["14040"]["edits"] == [
        {"by": "Ed Itor", "at": "2026-07-02 00:30"}
    ]


@pytest.mark.asyncio
async def test_save_db_error_keeps_old_code_and_buffer(db):
    db.error = RuntimeError("offline")
    buffer = dict(CODE, advice="New advice")
    update, _ = make_update("troubleshooter:code_edit_save")
    context, _ = make_context(user_data={"code_edit_buffer": buffer})

    with pytest.raises(RuntimeError, match="offline"):
        await admin_codes.button_code_edit_save(update, context)

    assert context.bot_data["codes"]["14040"]["advice"] == "Check the fuse"
    assert context.user_data["code_edit_buffer"]["advice"] == "New advice"
    assert db.notes == []


@pytest.mark.asyncio
async def test_save_without_buffer_returns_nothing(db):
    update, _ = make_update("troubleshooter:code_edit_save")
    context, _ = make_context()

    assert await admin_codes.button_code_edit_save(update, context) is None
    assert db.added == []


@pytest.mark.asyncio
async def test_times_use_uk_time_not_server_time(db):
    update, _ = make_update("troubleshooter:code_edit_save")
    context, _ = make_context(user_data={"code_edit_buffer": dict(CODE)})

    await admin_codes.button_code_edit_save(update, context)

    assert context.bot_data["codes"]["14040"]["edits"][-1]["at"] == "2026-07-02 00:30"
    assert admin.local_now() == NOW
    assert admin.local_now().tzinfo is None


TRICKY = {"advice": "Check PN_123 *now*", "parts": "PN_1 spare"}


@pytest.mark.asyncio
async def test_editor_escapes_advice_and_parts():
    context, record = make_context(user_data={"code_edit_buffer": dict(CODE, **TRICKY)})

    await admin_codes.handle_code_edit(context, 1, 55)

    text = record["edits"][0]["text"]
    assert "Check PN\\_123 \\*now\\*" in text
    assert "PN\\_1 spare" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, escaped",
    [("advice", "Check PN\\_123 \\*now\\*"), ("parts", "PN\\_1 spare")],
)
async def test_edit_field_escapes_current_value(field, escaped):
    update, calls = make_update(f"troubleshooter:code_edit_field:{field}")
    context, _ = make_context(user_data={"code_edit_buffer": dict(CODE, **TRICKY)})

    await admin_codes.button_code_edit_field(update, context)

    assert f"*Current:* {escaped}" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_editor_handles_empty_parts():
    context, record = make_context(
        user_data={"code_edit_buffer": dict(CODE, parts=None)}
    )

    await admin_codes.handle_code_edit(context, 1, 55)

    assert "*Parts:*\n\n" in record["edits"][0]["text"]
