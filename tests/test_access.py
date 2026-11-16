from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.db as db
from turbine_troubleshooter.blocks import user
from turbine_troubleshooter.blocks.admin import users as admin_users
from turbine_troubleshooter.settings import SETTINGS

OWNER = 999
STRANGER = 123


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


@pytest.fixture(autouse=True)
def no_db_requests(monkeypatch):
    saved = AsyncMock()
    monkeypatch.setattr(user, "request_add", saved)
    monkeypatch.setattr(admin_users, "request_remove", AsyncMock())
    return saved


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
    monkeypatch.setattr(
        turbine_troubleshooter, "user_add", AsyncMock(return_value=False)
    )
    block = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_block", block)
    message = SimpleNamespace(delete=AsyncMock(), reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=STRANGER, username="someone"),
    )

    await turbine_troubleshooter.command_handler(update, make_context())

    block.assert_not_awaited()
    text = message.reply_text.await_args.args[0]
    assert "Access is by approval" in text
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert callbacks(markup) == ["troubleshooter:access_request"]


@pytest.mark.parametrize(
    "data",
    ["troubleshooter:torque", "troubleshooter:code_search", "troubleshooter:home"],
)
@pytest.mark.asyncio
async def test_unapproved_user_buttons_show_lock_screen(monkeypatch, data):
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_button", handled)
    update, query = make_query(data)

    await turbine_troubleshooter.callback_handler(update, make_context())

    handled.assert_not_awaited()
    assert "Access is by approval" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("approved, owner_id", [({STRANGER}, OWNER), ((), STRANGER)])
@pytest.mark.asyncio
async def test_approved_user_and_owner_get_through(monkeypatch, approved, owner_id):
    monkeypatch.setattr(SETTINGS, "owner_id", str(owner_id))
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_button", handled)
    update, _ = make_query("troubleshooter:code_search")

    await turbine_troubleshooter.callback_handler(update, make_context(approved))

    handled.assert_awaited_once()


@pytest.mark.asyncio
async def test_unapproved_user_can_request_access(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_button", handled)
    update, _ = make_query("troubleshooter:access_request")

    await turbine_troubleshooter.callback_handler(update, make_context())

    handled.assert_awaited_once()


@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.asyncio
async def test_files_only_reach_suggestions_for_approved_users(monkeypatch, approved):
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter.suggest, "handle_file", handled)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=STRANGER))

    await turbine_troubleshooter.file_handler(
        update, make_context({STRANGER} if approved else ())
    )

    assert handled.await_count == (1 if approved else 0)


@pytest.mark.asyncio
async def test_unapproved_user_text_is_ignored(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_text_input", handled)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=STRANGER))

    await turbine_troubleshooter.text_handler(update, make_context())

    handled.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_access_notifies_owner_once(no_db_requests):
    context = make_context()
    update, query = make_query("troubleshooter:access_request")

    await user.button_request_access(update, context)
    await user.button_request_access(update, context)

    no_db_requests.assert_awaited_once_with(STRANGER, "access", "@someone")

    context.bot.send_message.assert_awaited_once()
    sent = context.bot.send_message.await_args.kwargs
    assert "Access Request" in sent["text"]
    assert callbacks(sent["reply_markup"]) == [
        f"troubleshooter:access:deny:{STRANGER}",
        f"troubleshooter:access:approve:{STRANGER}",
    ]
    assert "already waiting" in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_approval_grants_access(monkeypatch):
    approve = AsyncMock(return_value=True)
    monkeypatch.setattr(admin_users, "user_approve", approve)
    context = make_context()
    context.bot_data["pending_access_requests"] = {STRANGER: "@someone"}
    update, query = make_query(
        f"troubleshooter:access:approve:{STRANGER}", user_id=OWNER
    )

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
    update, query = make_query(
        f"troubleshooter:access:approve:{STRANGER}", user_id=STRANGER
    )

    await getattr(admin_users, handler)(update, context)

    approve.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    assert STRANGER not in context.bot_data["troubleshooter_approved"]


@pytest.mark.asyncio
async def test_owner_denial_tells_user(monkeypatch):
    approve = AsyncMock()
    monkeypatch.setattr(admin_users, "user_approve", approve)
    context = make_context()
    update, _ = make_query(f"troubleshooter:access:deny:{STRANGER}", user_id=OWNER)

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


@pytest.mark.asyncio
async def test_startup_loads_saved_requests(monkeypatch, make_cursor, patch_session):
    monkeypatch.setattr(SETTINGS.content, "IO_BOARDS", {})
    cur = make_cursor()

    async def fetchone():
        sql = cur.calls[-1][0]
        return {"t": sql.split("'")[1]} if sql.startswith("SHOW TABLES") else None

    async def fetchall():
        if cur.calls[-1][0] == "SELECT user_id, kind, name FROM requests":
            return [
                {"user_id": 5, "kind": "access", "name": "@five"},
                {"user_id": 6, "kind": "admin", "name": None},
                {"user_id": 7, "kind": "bogus", "name": "@x"},
            ]
        return []

    cur.fetchone = AsyncMock(side_effect=fetchone)
    cur.fetchall = AsyncMock(side_effect=fetchall)
    patch_session(db, cur)
    app = SimpleNamespace(bot_data={})

    await db.init_troubleshooter_db(app)

    assert app.bot_data["pending_access_requests"] == {5: "@five"}
    assert app.bot_data["pending_admin_requests"] == {6: "6"}
    assert not any("CREATE TABLE requests" in c[0] for c in cur.calls)


@pytest.mark.asyncio
async def test_requests_table_created_when_missing(make_cursor, patch_session):
    cur = make_cursor()
    patch_session(db, cur)

    await db.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert any("CREATE TABLE requests" in c[0] for c in cur.calls)


@pytest.mark.asyncio
async def test_user_get(make_cursor, patch_session):
    cur = make_cursor(
        fetchone=[
            {"user_id": "7", "username": "x", "is_admin": 0, "is_approved": 1},
            None,
        ]
    )
    patch_session(db, cur)

    found = await db.user_get(7)
    missing = await db.user_get(8)

    assert found["user_id"] == 7 and found["is_approved"] == 1
    assert missing is None
    assert cur.calls[0][0].endswith("FROM users WHERE user_id = %s")


@pytest.mark.asyncio
async def test_request_add_and_remove(make_cursor, patch_session):
    cur = make_cursor(rowcount=1)
    patch_session(db, cur)

    await db.request_add(7, "access", "@x")
    assert await db.request_remove(7) is True

    assert cur.calls[0][1] == (7, "access", "@x")
    assert cur.calls[1] == ("DELETE FROM requests WHERE user_id = %s", (7,))


@pytest.mark.asyncio
async def test_request_still_sent_when_db_save_fails(monkeypatch, no_db_requests):
    no_db_requests.side_effect = RuntimeError("offline")
    monkeypatch.setattr(user.sentry_sdk, "capture_exception", lambda e: None)
    context = make_context()
    update, _ = make_query("troubleshooter:access_request")

    await user.button_request_access(update, context)

    context.bot.send_message.assert_awaited_once()
    assert context.bot_data["pending_access_requests"] == {STRANGER: "@someone"}


@pytest.mark.asyncio
async def test_revoked_user_is_locked_out_straight_away(monkeypatch):
    handled = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "handle_button", handled)
    context = make_context(approved={STRANGER})
    context.bot_data["troubleshooter_approved"].discard(STRANGER)
    update, query = make_query("troubleshooter:code_search")

    await turbine_troubleshooter.callback_handler(update, context)

    handled.assert_not_awaited()
    assert "Access is by approval" in query.edit_message_text.await_args.args[0]


@pytest.mark.parametrize("rowcount, expected", [(1, True), (0, False)])
@pytest.mark.asyncio
async def test_user_revoke(make_cursor, patch_session, rowcount, expected):
    import turbine_troubleshooter.db as ts

    cur = make_cursor(rowcount=rowcount)
    patch_session(ts, cur)

    assert await ts.user_revoke(7) is expected
    assert cur.execute.call_args.args == (
        "UPDATE users SET is_approved = 0 WHERE user_id = %s",
        (7,),
    )
