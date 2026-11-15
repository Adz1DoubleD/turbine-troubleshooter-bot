from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import troubleshooter
import troubleshooter.db as db
from troubleshooter.blocks import user
from troubleshooter.blocks.admin import users as admin_users
from troubleshooter.settings import SETTINGS

OWNER = 999
STRANGER = 123


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


def make_context(approved=()):
    return SimpleNamespace(
        user_data={},
        bot_data={
            "is_troubleshooter": True,
            "troubleshooter_admins": {},
            "troubleshooter_approved": set(approved),
        },
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def make_query(data, user_id=STRANGER):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="someone", full_name="Some One"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), query


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_start_shows_request_access_to_unapproved_user(monkeypatch):
    monkeypatch.setattr(troubleshooter, "user_add", AsyncMock(return_value=False))
    block = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_block", block)
    message = SimpleNamespace(delete=AsyncMock(), reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=STRANGER, username="someone"),
    )

    await troubleshooter.command_handler(update, make_context())

    block.assert_not_awaited()
    text = message.reply_text.await_args.args[0]
    assert "Access is by approval" in text
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert callbacks(markup) == ["troubleshooter:access_request"]


@pytest.mark.parametrize(
    "data",
    ["troubleshooter:torque", "troubleshooter:code_search", "back:troubleshooter"],
)
@pytest.mark.asyncio
async def test_unapproved_user_buttons_show_lock_screen(monkeypatch, data):
    handled = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_button", handled)
    update, query = make_query(data)

    await troubleshooter.callback_handler(update, make_context())

    handled.assert_not_awaited()
    assert "Access is by approval" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("approved, owner_id", [({STRANGER}, OWNER), ((), STRANGER)])
@pytest.mark.asyncio
async def test_approved_user_and_owner_get_through(monkeypatch, approved, owner_id):
    monkeypatch.setattr(SETTINGS, "owner_id", str(owner_id))
    handled = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_button", handled)
    update, _ = make_query("troubleshooter:code_search")

    await troubleshooter.callback_handler(update, make_context(approved))

    handled.assert_awaited_once()


@pytest.mark.asyncio
async def test_unapproved_user_can_request_access(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_button", handled)
    update, _ = make_query("troubleshooter:access_request")

    await troubleshooter.callback_handler(update, make_context())

    handled.assert_awaited_once()


@pytest.mark.asyncio
async def test_unapproved_user_text_is_ignored(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_text_input", handled)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=STRANGER))

    await troubleshooter.text_handler(update, make_context())

    handled.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_access_notifies_owner_once():
    context = make_context()
    update, query = make_query("troubleshooter:access_request")

    await user.button_request_access(update, context)
    await user.button_request_access(update, context)

    context.bot.send_message.assert_awaited_once()
    sent = context.bot.send_message.await_args.kwargs
    assert "Access Request" in sent["text"]
    assert callbacks(sent["reply_markup"]) == [
        f"access:deny:{STRANGER}",
        f"access:approve:{STRANGER}",
    ]
    assert "already waiting" in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_approval_grants_access(monkeypatch):
    approve = AsyncMock(return_value=True)
    monkeypatch.setattr(admin_users, "user_approve", approve)
    context = make_context()
    context.bot_data["pending_access_requests"] = {STRANGER: "@someone"}
    update, query = make_query(f"access:approve:{STRANGER}", user_id=OWNER)

    await admin_users.button_access_approve(update, context)

    approve.assert_awaited_once_with(STRANGER)
    assert STRANGER in context.bot_data["troubleshooter_approved"]
    assert context.bot.send_message.await_args.args[0] == STRANGER
    assert "access" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("handler", ["button_access_approve", "button_access_deny"])
@pytest.mark.asyncio
async def test_only_owner_can_decide_access(monkeypatch, handler):
    approve = AsyncMock()
    monkeypatch.setattr(admin_users, "user_approve", approve)
    context = make_context()
    update, query = make_query(f"access:approve:{STRANGER}", user_id=STRANGER)

    await getattr(admin_users, handler)(update, context)

    approve.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    assert STRANGER not in context.bot_data["troubleshooter_approved"]


@pytest.mark.asyncio
async def test_owner_denial_tells_user(monkeypatch):
    approve = AsyncMock()
    monkeypatch.setattr(admin_users, "user_approve", approve)
    context = make_context()
    update, _ = make_query(f"access:deny:{STRANGER}", user_id=OWNER)

    await admin_users.button_access_deny(update, context)

    approve.assert_not_awaited()
    assert "declined" in context.bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_startup_loads_approved_users(monkeypatch, make_cursor, patch_session):
    monkeypatch.setattr(SETTINGS.content, "IO_BOARDS", {})
    cur = make_cursor(
        fetchone=[{"t": "content"}, {"t": "codes"}, {"t": "users"}, {"t": "parts"}],
        fetchall=[[], [], [], [{"user_id": 5}, {"user_id": 6}], []],
    )
    patch_session(db, cur)
    app = SimpleNamespace(bot_data={})

    await db.init_troubleshooter_db(app)

    sql = [c.args[0] for c in cur.execute.call_args_list]
    assert "SELECT user_id FROM users WHERE is_approved = 1 OR is_admin = 1" in sql
    assert not any("ALTER TABLE" in s for s in sql)
    assert app.bot_data["troubleshooter_approved"] == {5, 6}


USERS = [
    {"user_id": 1, "username": "zed", "is_approved": 1, "is_admin": 0},
    {"user_id": 2, "username": "amy", "is_approved": 1, "is_admin": 0},
    {"user_id": 3, "username": "boss", "is_approved": 1, "is_admin": 1},
    {"user_id": 4, "username": "new", "is_approved": 0, "is_admin": 0},
]


@pytest.mark.asyncio
async def test_access_list_shows_approved_non_admins(monkeypatch):
    monkeypatch.setattr(admin_users, "users_get", AsyncMock(return_value=USERS))
    update, query = make_query("troubleshooter:access_list", user_id=OWNER)

    await admin_users.button_access_list(update, make_context())

    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert callbacks(markup) == [
        "troubleshooter:access_revoke:2",
        "troubleshooter:access_revoke:1",
        "troubleshooter:admin_menu",
    ]


@pytest.mark.asyncio
async def test_revoke_removes_access_and_tells_user(monkeypatch):
    revoke = AsyncMock(return_value=True)
    notify = AsyncMock()
    monkeypatch.setattr(admin_users, "user_revoke", revoke)
    monkeypatch.setattr(admin_users, "send_notification_troubleshooter", notify)
    monkeypatch.setattr(admin_users, "users_get", AsyncMock(return_value=[]))
    context = make_context(approved={STRANGER})
    update, query = make_query(f"troubleshooter:access_revoke:{STRANGER}", OWNER)

    await admin_users.button_access_revoke(update, context)

    revoke.assert_awaited_once_with(STRANGER)
    assert STRANGER not in context.bot_data["troubleshooter_approved"]
    notify.assert_awaited_once_with(action="access_revoked", target_id=STRANGER)
    assert "Access removed" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("handler", ["button_access_list", "button_access_revoke"])
@pytest.mark.asyncio
async def test_only_owner_can_manage_access(monkeypatch, handler):
    revoke = AsyncMock()
    monkeypatch.setattr(admin_users, "user_revoke", revoke)
    context = make_context(approved={STRANGER})
    update, query = make_query(f"troubleshooter:access_revoke:{STRANGER}", 555)

    await getattr(admin_users, handler)(update, context)

    revoke.assert_not_awaited()
    assert STRANGER in context.bot_data["troubleshooter_approved"]
    assert "Unauthorized" in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_revoked_user_is_locked_out_straight_away(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(troubleshooter, "handle_button", handled)
    context = make_context(approved={STRANGER})
    context.bot_data["troubleshooter_approved"].discard(STRANGER)
    update, query = make_query("troubleshooter:code_search")

    await troubleshooter.callback_handler(update, context)

    handled.assert_not_awaited()
    assert "Access is by approval" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("rowcount, expected", [(1, True), (0, False)])
@pytest.mark.asyncio
async def test_user_revoke(make_cursor, patch_session, rowcount, expected):
    import troubleshooter.db as ts

    cur = make_cursor(rowcount=rowcount)
    patch_session(ts, cur)

    assert await ts.user_revoke(7) is expected
    assert cur.execute.call_args.args == (
        "UPDATE users SET is_approved = 0 WHERE user_id = %s",
        (7,),
    )
