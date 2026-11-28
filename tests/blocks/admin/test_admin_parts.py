from datetime import datetime
from types import SimpleNamespace

import pytest

import turbine_troubleshooter.blocks.admin as admin
from turbine_troubleshooter.blocks.admin import parts

OWNER = 123
OTHER = 456
OTHER_PART = {"id": 8, "part_no": "PN00400485", "description": "Other"}
NOW = datetime(2026, 7, 2, 0, 30)


@pytest.fixture(autouse=True)
def owner_is_the_user(monkeypatch):
    from turbine_troubleshooter.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(admin, "local_now", lambda: NOW)
    monkeypatch.setattr(parts, "local_now", lambda: NOW)


def make_update(data=None, user_id=OWNER, with_query=True):
    calls = {"answers": [], "edits": [], "deleted": False}

    async def answer(text=None, **kwargs):
        calls["answers"].append(text)

    async def edit_message_text(text=None, **kwargs):
        calls["edits"].append({"text": text, **kwargs})

    async def delete():
        calls["deleted"] = True

    query = (
        SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(message_id=55),
            answer=answer,
            edit_message_text=edit_message_text,
        )
        if with_query
        else None
    )

    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, username="editor", full_name="Ed"),
        effective_chat=SimpleNamespace(id=user_id),
        message=SimpleNamespace(delete=delete),
    )
    return update, calls


def make_context(is_admin=True, user_data=None, bot_data=None):
    bot_edits = []

    async def edit_message_text(**kwargs):
        bot_edits.append(kwargs)

    context = SimpleNamespace(
        user_data={"is_admin": is_admin, **(user_data or {})},
        bot_data=bot_data if bot_data is not None else {},
        bot=SimpleNamespace(edit_message_text=edit_message_text),
    )
    return context, bot_edits


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


PART = {
    "id": 7,
    "part_no": "PN00400484",
    "description": "YAW MOTOR",
    "location": "B016",
}


def part_context(**kwargs):
    return make_context(bot_data={"parts": [dict(PART), dict(OTHER_PART)]}, **kwargs)


@pytest.fixture
def part_notes(monkeypatch):
    notes = []

    async def fake_notify(*args, **kwargs):
        notes.append((args, kwargs))
        return 0, 0, []

    monkeypatch.setattr(parts, "send_notification_troubleshooter", fake_notify)
    return notes


@pytest.mark.asyncio
async def test_part_edit_shows_fields_and_remove():
    update, _ = make_update("troubleshooter:part_edit:7")
    update.callback_query.message.chat_id = 1
    context, bot_edits = part_context(user_data={"state": "something"})

    await parts.button_part_edit(update, context)

    assert callbacks(bot_edits[0]["reply_markup"])[:5] == [
        "troubleshooter:part_edit_field:part_no:7",
        "troubleshooter:part_edit_field:stock_no:7",
        "troubleshooter:part_edit_field:location:7",
        "troubleshooter:part_edit_field:description:7",
        "troubleshooter:part_confirm_del:7",
    ]
    assert "`PN00400484`" in bot_edits[0]["text"]
    assert context.user_data["state"] is None
    assert context.user_data["last_msg_id"] == 55


@pytest.mark.asyncio
async def test_part_edit_missing_part():
    update, calls = make_update("troubleshooter:part_edit:99")
    context, bot_edits = part_context()

    await parts.button_part_edit(update, context)

    assert bot_edits == []
    assert "not found" in calls["answers"][0]


@pytest.mark.asyncio
async def test_part_edit_rejects_non_admin():
    update, calls = make_update("troubleshooter:part_edit:7", user_id=OTHER)
    context, bot_edits = part_context(is_admin=False)

    await parts.button_part_edit(update, context)

    assert bot_edits == []
    assert "Unauthorized" in calls["answers"][0]


@pytest.mark.asyncio
async def test_part_edit_field_sets_state_and_prompt():
    update, calls = make_update("troubleshooter:part_edit_field:description:7")
    context, _ = part_context()

    await parts.button_part_edit_field(update, context)

    assert context.user_data["state"] == "troubleshooter:part_await_edit:description:7"
    assert "YAW MOTOR" in calls["edits"][0]["text"]
    assert callbacks(calls["edits"][0]["reply_markup"]) == [
        "troubleshooter:part_edit:7"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,text,saved_value,change",
    [
        ("part_no", " pn999 ", "PN999", "Part No: PN00400484 → PN999"),
        ("stock_no", " 10255168 ", "10255168", "Stock No: None → 10255168"),
        (
            "description",
            "New desc",
            "New desc",
            "Description: YAW MOTOR → New desc",
        ),
        ("location", "-", "", "Location: B016 → None"),
        ("location", " a005 ", "A005", "Location: B016 → A005"),
    ],
)
async def test_part_edit_saves_field(
    monkeypatch, part_notes, field, text, saved_value, change
):
    saved = []

    async def fake_update(part_id, f, value, edited_by=None, edited_at=None, old=None):
        saved.append((part_id, f, value, edited_by, edited_at))
        return True

    monkeypatch.setattr(parts, "part_update", fake_update)
    update, _ = make_update(with_query=False)
    context, bot_edits = part_context(user_data={"last_msg_id": 55})
    state = f"troubleshooter:part_await_edit:{field}:7"

    await parts.handle_part_edit(update, context, text, state)

    part = context.bot_data["parts"][0]
    assert saved == [(7, field, saved_value, "@editor", "2026-07-02 00:30")]
    assert part[field] == saved_value
    assert part["edits"][0]["by"] == "@editor"
    assert part["edits"][0]["at"] == "2026-07-02 00:30"
    assert part["edits"][0]["changes"][field][1] == saved_value
    assert "✅ *Saved*" in bot_edits[0]["text"]
    assert bot_edits[0]["message_id"] == 55
    assert context.user_data["state"] is None
    assert part_notes == [
        (
            (
                update.effective_user,
                "part_edited",
                part["part_no"],
                part["description"],
            ),
            {"message": change, "undo": None},
        )
    ]


@pytest.mark.asyncio
async def test_part_edit_adding_a_location_shows_none_as_old_value(
    monkeypatch, part_notes
):
    async def fake_update(*args, **kwargs):
        return True

    monkeypatch.setattr(parts, "part_update", fake_update)
    update, _ = make_update(with_query=False)
    context, _ = part_context()

    await parts.handle_part_edit(
        update, context, "b016", "troubleshooter:part_await_edit:location:8"
    )

    assert part_notes[0][1] == {"message": "Location: None → B016", "undo": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,text,message",
    [
        ("part_no", "pn00400485", "already exists"),
        ("description", "   ", "can't be empty"),
        ("description", "YAW MOTOR", "No change"),
        ("part_no", " pn00400484 ", "No change"),
    ],
    ids=["duplicate", "empty", "same-description", "same-part-no"],
)
async def test_part_edit_refuses_bad_values(
    monkeypatch, part_notes, field, text, message
):
    async def fail_update(*args):
        raise AssertionError("must not save")

    monkeypatch.setattr(parts, "part_update", fail_update)
    update, _ = make_update(with_query=False)
    context, bot_edits = part_context()

    await parts.handle_part_edit(
        update, context, text, f"troubleshooter:part_await_edit:{field}:7"
    )

    assert message in bot_edits[0]["text"]
    assert context.bot_data["parts"][0] == PART
    assert part_notes == []


@pytest.mark.asyncio
async def test_part_edit_db_failure_leaves_part_unchanged(monkeypatch, part_notes):
    async def fake_update(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(parts, "part_update", fake_update)
    update, _ = make_update(with_query=False)
    context, _ = part_context()

    with pytest.raises(RuntimeError, match="offline"):
        await parts.handle_part_edit(
            update, context, "New desc", "troubleshooter:part_await_edit:description:7"
        )

    assert context.bot_data["parts"][0] == PART
    assert "edits" not in context.bot_data["parts"][0]
    assert part_notes == []


@pytest.mark.asyncio
async def test_part_delete_confirm_cancel_returns_to_part():
    update, calls = make_update("troubleshooter:part_confirm_del:7")
    context, _ = part_context()

    await parts.button_part_delete_confirm(update, context)

    assert callbacks(calls["edits"][0]["reply_markup"]) == [
        "troubleshooter:part_edit:7",
        "troubleshooter:part_delete:7",
    ]


@pytest.mark.asyncio
async def test_part_add_flow(monkeypatch):
    added = []

    async def fake_add(
        part_no, description, added_by=None, stock_no=None, location=None
    ):
        added.append(
            {
                "part_no": part_no,
                "description": description,
                "added_by": added_by,
                "stock_no": stock_no,
                "location": location,
            }
        )
        return 42

    async def fake_block(update, context, status=None):
        context.user_data["status"] = status

    notes = []

    async def fake_notify(*args, **kwargs):
        notes.append(args)
        return 0, 0, []

    monkeypatch.setattr(parts, "part_add", fake_add)
    monkeypatch.setattr(parts, "handle_block", fake_block)
    monkeypatch.setattr(parts, "send_notification_troubleshooter", fake_notify)

    context, bot_edits = make_context(
        user_data={"last_msg_id": 9}, bot_data={"parts": []}
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1), effective_user=editor
    )

    await parts.handle_part_add(
        update, context, "pn123", "troubleshooter:part_add:part_no"
    )
    assert context.user_data["state"] == "troubleshooter:part_add:description"
    assert "`PN123`" in bot_edits[-1]["text"]

    await parts.handle_part_add(update, context, "New pump", context.user_data["state"])
    assert context.user_data["state"] == "troubleshooter:part_add:stock_no"
    assert "Stock No" in bot_edits[-1]["text"]
    assert added == []

    await parts.handle_part_add(
        update, context, " 10255168 ", context.user_data["state"]
    )
    assert context.user_data["state"] == "troubleshooter:part_add:location"
    assert "Step 4" in bot_edits[-1]["text"]
    assert "Location" in bot_edits[-1]["text"]
    assert added == []

    await parts.handle_part_add(update, context, " b016 ", context.user_data["state"])

    assert added == [
        {
            "part_no": "PN123",
            "description": "New pump",
            "added_by": "@editor",
            "stock_no": "10255168",
            "location": "B016",
        }
    ]
    assert context.bot_data["parts"] == [
        {
            "id": 42,
            "added_by": "@editor",
            "edits": [],
            "part_no": "PN123",
            "description": "New pump",
            "stock_no": "10255168",
            "location": "B016",
        }
    ]
    assert context.user_data["state"] is None
    assert "Part Added" in context.user_data["status"]
    assert notes == [(editor, "part_added", "PN123", "New pump")]


@pytest.mark.asyncio
async def test_part_add_stops_if_part_exists():
    context, bot_edits = part_context(
        user_data={"state": "troubleshooter:part_add:part_no", "last_msg_id": 9}
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))

    await parts.handle_part_add(
        update, context, "pn00400484", "troubleshooter:part_add:part_no"
    )

    assert "already exists" in bot_edits[-1]["text"]
    assert "YAW MOTOR" in bot_edits[-1]["text"]
    assert context.user_data["state"] is None
    assert "new_part" not in context.user_data
    assert callbacks(bot_edits[-1]["reply_markup"]) == [
        "troubleshooter:part_edit:7",
        "troubleshooter:admin_menu",
    ]


@pytest.mark.asyncio
async def test_part_delete_removes_from_ram(monkeypatch):
    deleted = []

    async def fake_delete(table, column, value):
        deleted.append((table, column, value))
        return True

    async def fake_block(update, context, status=None):
        context.user_data["status"] = status

    notes = []

    async def fake_notify(*args, **kwargs):
        notes.append(args)
        return 0, 0, []

    monkeypatch.setattr(parts, "delete_entry", fake_delete)
    monkeypatch.setattr(parts, "handle_block", fake_block)
    monkeypatch.setattr(parts, "send_notification_troubleshooter", fake_notify)

    context, _ = make_context(bot_data={"parts": [dict(PART)]})
    update, _ = make_update("troubleshooter:part_delete:7")

    await parts.button_part_delete(update, context)

    assert deleted == [("parts", "id", 7)]
    assert context.bot_data["parts"] == []
    assert "removed" in context.user_data["status"]
    assert notes[0][1:] == ("part_deleted", "PN00400484", "YAW MOTOR")


@pytest.mark.asyncio
async def test_part_delete_not_found_does_not_notify(monkeypatch):
    async def fake_delete(table, column, value):
        return False

    async def fake_block(update, context, status=None):
        context.user_data["status"] = status

    async def fail_notify(*args, **kwargs):
        raise AssertionError("failed delete must not notify")

    monkeypatch.setattr(parts, "delete_entry", fake_delete)
    monkeypatch.setattr(parts, "handle_block", fake_block)
    monkeypatch.setattr(parts, "send_notification_troubleshooter", fail_notify)

    context, _ = make_context(bot_data={"parts": [dict(PART)]})
    update, _ = make_update("troubleshooter:part_delete:7")

    await parts.button_part_delete(update, context)

    assert len(context.bot_data["parts"]) == 1
    assert "not found" in context.user_data["status"]


@pytest.mark.asyncio
async def test_part_edit_adds_to_existing_history(monkeypatch, part_notes):
    async def fake_update(*args, **kwargs):
        return True

    monkeypatch.setattr(parts, "part_update", fake_update)
    update, _ = make_update(with_query=False)
    context, _ = part_context()
    context.bot_data["parts"][0]["edits"] = [{"by": "@bob", "at": "x"}]

    await parts.handle_part_edit(
        update, context, "New desc", "troubleshooter:part_await_edit:description:7"
    )

    assert context.bot_data["parts"][0]["edits"] == [
        {"by": "@bob", "at": "x"},
        {
            "by": "@editor",
            "at": "2026-07-02 00:30",
            "changes": {"description": ["YAW MOTOR", "New desc"]},
        },
    ]


@pytest.mark.asyncio
async def test_part_add_uses_full_name_without_username(monkeypatch):
    added = []

    async def fake_add(
        part_no, description, added_by=None, stock_no=None, location=None
    ):
        added.append((added_by, stock_no, location))
        return 42

    async def fake_block(update, context, status=None):
        pass

    async def fake_notify(*args, **kwargs):
        return 0, 0, []

    monkeypatch.setattr(parts, "part_add", fake_add)
    monkeypatch.setattr(parts, "handle_block", fake_block)
    monkeypatch.setattr(parts, "send_notification_troubleshooter", fake_notify)
    context, _ = make_context(
        user_data={"new_part": {"part_no": "PN1", "description": "Pump"}},
        bot_data={"parts": []},
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=5, username=None, full_name="Ed Itor"),
    )

    await parts.handle_part_add(
        update, context, "-", "troubleshooter:part_add:location"
    )

    assert added == [("Ed Itor", None, "")]
