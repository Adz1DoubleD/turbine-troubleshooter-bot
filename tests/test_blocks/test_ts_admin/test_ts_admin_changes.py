from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.tools as tools
from turbine_troubleshooter.blocks.admin import changes
from turbine_troubleshooter.blocks.admin import codes as admin_codes
from turbine_troubleshooter.blocks.admin import parts as admin_parts
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5
ALERTS = "-100"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", ALERTS)
    monkeypatch.setattr(
        changes, "local_now", lambda: SimpleNamespace(strftime=lambda f: "NOW")
    )


@pytest.fixture
def db(monkeypatch):
    m = SimpleNamespace(
        requests=[], removed=[], deleted=[], codes=[], parts=[], notes=[], told=[]
    )
    m.next_id = 9

    async def request_add(kind, target, label, user_id, name):
        if any(r[:2] == (kind, str(target)) for r in m.requests):
            return None
        m.requests.append((kind, str(target), label, user_id, name))
        return m.next_id

    async def request_remove(request_id):
        m.removed.append(request_id)
        return True

    async def delete_entry(table, column, value):
        m.deleted.append((table, column, value))
        return True

    async def code_add(**kwargs):
        m.codes.append(kwargs)

    async def part_update(*args, **kwargs):
        m.parts.append((args, kwargs))

    async def notify(*args, **kwargs):
        m.notes.append((args, kwargs))

    async def tell(context, user_id, text, reply_markup=None):
        m.told.append((user_id, text))

    for module in (changes, admin_codes, admin_parts):
        monkeypatch.setattr(module, "send_notification_troubleshooter", notify)
    monkeypatch.setattr(changes, "delete_request_add", request_add)
    monkeypatch.setattr(changes, "delete_request_remove", request_remove)
    monkeypatch.setattr(changes, "delete_entry", delete_entry)
    monkeypatch.setattr(changes, "fault_code_add", code_add)
    monkeypatch.setattr(changes, "part_update", part_update)
    monkeypatch.setattr(changes, "tell_user", tell)
    monkeypatch.setattr(admin_codes, "delete_entry", delete_entry)
    monkeypatch.setattr(admin_parts, "delete_entry", delete_entry)
    return m


def make(data, user_id, bot_data=None):
    user = SimpleNamespace(
        id=user_id, username="ann" if user_id == ADMIN else "own", full_name="X"
    )
    query = SimpleNamespace(
        data=data,
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(message_id=3, chat_id=user_id),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
        send_chat_action=AsyncMock(),
    )
    context = SimpleNamespace(
        bot=bot,
        bot_data={
            "is_troubleshooter": True,
            "codes": {
                "E1": {
                    "id": 2,
                    "code": "E1",
                    "advice": "Old",
                    "parts": "P",
                    "edits": [],
                }
            },
            "parts": [
                {
                    "id": 7,
                    "part_no": "PN7",
                    "description": "Pump",
                    "section": "",
                    "edits": [],
                }
            ],
            "pending_delete_requests": {},
            **(bot_data or {}),
        },
        user_data={"is_admin": True},
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=user,
        effective_chat=SimpleNamespace(id=user_id),
    )
    return update, context


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_admin_code_delete_asks_the_owner(db):
    update, context = make("troubleshooter:code_delete:E1", ADMIN)

    status = await admin_codes.button_code_delete(update, context)

    assert db.deleted == []
    assert "E1" in context.bot_data["codes"]
    assert db.requests == [("code", "E1", "E1", ADMIN, "@ann")]
    assert context.bot_data["pending_delete_requests"][9]["label"] == "E1"
    sent = context.bot.send_message.await_args
    assert sent.args[0] == ALERTS
    assert "@ann wants to delete the code: E1" in sent.args[1]
    assert buttons(sent.kwargs["reply_markup"]) == [
        "troubleshooter:delreq:yes:9",
        "troubleshooter:delreq:no:9",
    ]
    assert "Sent to the owner" in status


@pytest.mark.asyncio
async def test_asking_twice_does_not_send_another_request(db):
    update, context = make("troubleshooter:code_delete:E1", ADMIN)
    await admin_codes.button_code_delete(update, context)

    status = await admin_codes.button_code_delete(update, context)

    assert "already been asked" in status
    assert context.bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_owner_code_delete_happens_at_once(db):
    update, context = make("troubleshooter:code_delete:E1", OWNER)

    await admin_codes.button_code_delete(update, context)

    assert db.deleted == [("codes", "code", "E1")]
    assert db.requests == []


@pytest.mark.asyncio
async def test_admin_part_delete_asks_the_owner(db, monkeypatch):
    monkeypatch.setattr(admin_parts, "handle_block", AsyncMock())
    update, context = make("troubleshooter:part_delete:7", ADMIN)

    await admin_parts.button_part_delete(update, context)

    assert db.deleted == []
    assert db.requests == [("part", "7", "PN7 – Pump", ADMIN, "@ann")]
    assert len(context.bot_data["parts"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,label", [(OWNER, "✅ Yes, Delete"), (ADMIN, "✅ Yes, Ask the Owner")]
)
async def test_confirm_screen_says_who_deletes(db, who, label):
    update, context = make("troubleshooter:code_confirm_del:E1", who)

    await admin_codes.button_code_delete_confirm(update, context)

    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    assert label in [b.text for row in markup.inline_keyboard for b in row]


def waiting(kind="code", target="E1", label="E1"):
    return {
        "pending_delete_requests": {
            9: {
                "id": 9,
                "kind": kind,
                "target": target,
                "label": label,
                "user_id": ADMIN,
                "name": "@ann",
            }
        }
    }


@pytest.mark.asyncio
async def test_owner_approving_a_code_request_deletes_it(db):
    update, context = make("troubleshooter:delreq:yes:9", OWNER, waiting())

    await changes.button_delete_requests(update, context)

    assert db.deleted == [("codes", "code", "E1")]
    assert "E1" not in context.bot_data["codes"]
    assert db.removed == [9]
    assert context.bot_data["pending_delete_requests"] == {}
    assert db.told == [(ADMIN, "✅ The owner deleted the code you asked about: E1")]
    assert db.notes[0][0][1:] == ("code_deleted", "E1")
    assert (
        "✅ Deleted the code: E1"
        in update.callback_query.edit_message_text.await_args.args[0]
    )


@pytest.mark.asyncio
async def test_owner_approving_a_part_request_deletes_it(db):
    update, context = make(
        "troubleshooter:delreq:yes:9", OWNER, waiting("part", "7", "PN7 – Pump")
    )

    await changes.button_delete_requests(update, context)

    assert db.deleted == [("parts", "id", 7)]
    assert context.bot_data["parts"] == []
    assert db.notes[0][0][1:] == ("part_deleted", "PN7", "Pump")


@pytest.mark.asyncio
async def test_owner_keeping_an_item_tells_the_admin(db):
    update, context = make("troubleshooter:delreq:no:9", OWNER, waiting())

    await changes.button_delete_requests(update, context)

    assert db.deleted == []
    assert "E1" in context.bot_data["codes"]
    assert db.removed == [9]
    assert db.told == [(ADMIN, "❌ The owner kept the code you asked to delete: E1")]


@pytest.mark.asyncio
async def test_request_already_dealt_with(db):
    update, context = make("troubleshooter:delreq:yes:9", OWNER)

    await changes.button_delete_requests(update, context)

    assert db.deleted == [] and db.told == []
    assert (
        "already been dealt with"
        in update.callback_query.edit_message_text.await_args.args[0]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "troubleshooter:delreq",
        "troubleshooter:delreq:yes:9",
        "troubleshooter:undo:code:2:0",
    ],
)
async def test_only_the_owner_decides(db, data):
    update, context = make(data, ADMIN, waiting())

    handler = changes.button_undo if "undo" in data else changes.button_delete_requests
    await handler(update, context)

    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Only the owner can do that.", show_alert=True
    )
    assert db.deleted == [] and db.codes == []
    assert 9 in context.bot_data["pending_delete_requests"]


@pytest.mark.asyncio
async def test_one_inbox_lists_every_kind_of_request(db):
    update, context = make("troubleshooter:pending", OWNER, waiting())
    context.bot_data["pending_access_requests"] = {3: "@new"}

    await changes.button_pending(update, context)

    args = update.callback_query.edit_message_text.await_args
    assert "Requests</b> (2)" in args.args[0]
    assert "• @new wants access" in args.args[0]
    assert "• @ann wants to delete the code: E1" in args.args[0]
    assert buttons(args.kwargs["reply_markup"]) == [
        "troubleshooter:access:approve:3:p",
        "troubleshooter:access:deny:3:p",
        "troubleshooter:delreq:yes:9:p",
        "troubleshooter:delreq:no:9:p",
        "troubleshooter:admin_menu",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,back_to_inbox",
    [("troubleshooter:delreq:no:9:p", True), ("troubleshooter:delreq:no:9", False)],
)
async def test_decision_returns_to_where_it_was_made(db, data, back_to_inbox):
    update, context = make(data, OWNER, waiting())

    await changes.button_delete_requests(update, context)

    args = update.callback_query.edit_message_text.await_args
    assert args.args[0].startswith("❌ Kept the code: E1")
    assert ("Nothing waiting." in args.args[0]) is back_to_inbox
    assert buttons(args.kwargs["reply_markup"])[-1] == (
        "troubleshooter:admin_menu" if back_to_inbox else "cancel"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,undo", [(ADMIN, "troubleshooter:undo:code:2:0"), (OWNER, None)]
)
async def test_code_edit_by_an_admin_offers_undo(db, monkeypatch, who, undo):
    monkeypatch.setattr(admin_codes, "fault_code_add", AsyncMock())
    update, context = make("troubleshooter:code_edit_save", who)
    context.user_data["code_edit_buffer"] = {
        **context.bot_data["codes"]["E1"],
        "advice": "New",
    }

    await admin_codes.button_code_edit_save(update, context)

    assert context.bot_data["codes"]["E1"]["edits"][-1]["changes"] == {
        "advice": ["Old", "New"]
    }
    assert db.notes[0][1]["undo"] == undo
    assert db.notes[0][1]["was"] == "Advice: Old"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,undo", [(ADMIN, "troubleshooter:undo:part:7:0"), (OWNER, None)]
)
async def test_part_edit_by_an_admin_offers_undo(db, monkeypatch, who, undo):
    monkeypatch.setattr(admin_parts, "part_update", AsyncMock())
    update, context = make(None, who)
    context.user_data["last_msg_id"] = 3

    await admin_parts.handle_part_edit(
        update, context, "Valve", "troubleshooter:part_await_edit:description:7"
    )

    assert context.bot_data["parts"][0]["edits"][-1]["changes"] == {
        "description": ["Pump", "Valve"]
    }
    assert db.notes[0][1]["undo"] == undo


@pytest.mark.asyncio
async def test_owner_undoes_a_code_edit(db):
    code = {
        "id": 2,
        "code": "E1",
        "advice": "New",
        "parts": "P",
        "edits": [{"by": "@ann", "at": "x", "changes": {"advice": ["Old", "New"]}}],
    }
    update, context = make(
        "troubleshooter:undo:code:2:0", OWNER, {"codes": {"E1": code}}
    )

    await changes.button_undo(update, context)

    assert db.codes == [
        {
            "code": "E1",
            "advice": "Old",
            "parts": "P",
            "edited_by": "@own",
            "edited_at": "NOW",
            "changes": {"advice": ["New", "Old"]},
        }
    ]
    assert code["advice"] == "Old"
    assert code["edits"][-1] == {
        "by": "@own",
        "at": "NOW",
        "changes": {"advice": ["New", "Old"]},
    }
    update.callback_query.answer.assert_awaited_once_with("↩️ Undone.", show_alert=True)
    assert buttons(
        update.callback_query.edit_message_reply_markup.await_args.args[0]
    ) == ["cancel"]


@pytest.mark.asyncio
async def test_owner_undoes_a_part_edit(db):
    part = {
        "id": 7,
        "part_no": "PN7",
        "description": "Valve",
        "section": "",
        "edits": [
            {"by": "@ann", "at": "x", "changes": {"description": ["Pump", "Valve"]}}
        ],
    }
    update, context = make("troubleshooter:undo:part:7:0", OWNER, {"parts": [part]})

    await changes.button_undo(update, context)

    assert db.parts == [((7, "description", "Pump", "@own", "NOW"), {"old": "Valve"})]
    assert part["description"] == "Pump"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "advice,edits,message",
    [
        (
            "Newer",
            [{"by": "@ann", "at": "x", "changes": {"advice": ["Old", "New"]}}],
            "changed again since",
        ),
        ("New", [{"by": "@ann", "at": "x"}], "can't be undone any more"),
        ("New", [], "can't be undone any more"),
    ],
    ids=["changed-since", "old-history", "missing"],
)
async def test_undo_refused(db, advice, edits, message):
    code = {"id": 2, "code": "E1", "advice": advice, "parts": "P", "edits": edits}
    update, context = make(
        "troubleshooter:undo:code:2:0", OWNER, {"codes": {"E1": code}}
    )

    await changes.button_undo(update, context)

    assert db.codes == []
    assert code["advice"] == advice
    assert message in update.callback_query.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("alerts", ["1", "-100"], ids=["no-alerts-chat", "alerts-chat"])
async def test_undo_goes_to_the_alerts_chat_once(monkeypatch, alerts):
    bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(turbine_troubleshooter, "application", SimpleNamespace(bot=bot))
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", alerts)
    monkeypatch.setattr(tools, "users_get", AsyncMock(return_value=[]))
    user = SimpleNamespace(id=ADMIN, username="ann", full_name="Ann")

    await tools.send_notification_troubleshooter(
        user,
        "code_edited",
        "E1",
        "New",
        "P",
        undo="troubleshooter:undo:code:2:0",
        was="Advice: Old",
    )

    calls = [c.kwargs for c in bot.send_message.await_args_list]
    assert [(c["chat_id"], "Was:" in c["text"]) for c in calls] == [(alerts, True)]
    assert buttons(calls[0]["reply_markup"]) == [
        "troubleshooter:undo:code:2:0",
        "cancel",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("who,shown", [(OWNER, ["📥 Requests (1)"]), (ADMIN, [])])
async def test_admin_panel_shows_delete_requests_to_the_owner(who, shown):
    from turbine_troubleshooter.blocks import admin

    update, context = make("troubleshooter:admin_menu", who, waiting())

    await admin.handle_block(update, context)

    markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    assert [
        b.text for row in markup.inline_keyboard for b in row if "Requests" in b.text
    ] == shown
