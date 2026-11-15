from types import SimpleNamespace

import pytest

from troubleshooter.blocks.admin import users
from troubleshooter.settings import SETTINGS

OWNER = 123
OTHER = 456


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


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
        effective_user=SimpleNamespace(id=user_id),
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


def add_send_recorder(context):
    sent = []

    async def send_message(chat_id, text=None, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})

    context.bot.send_message = send_message
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize("removed,notified", [(True, True), (False, False)])
async def test_revoke_admin_notifies_only_on_success(monkeypatch, removed, notified):
    notes = []

    async def fake_remove(target_id):
        return removed

    async def fake_notify(**kwargs):
        notes.append(kwargs)

    monkeypatch.setattr(users, "admin_remove", fake_remove)
    monkeypatch.setattr(users, "send_notification_troubleshooter", fake_notify)

    update, _ = make_update("troubleshooter:admin_revoke:7")
    context, _ = make_context(bot_data={"troubleshooter_admins": {7: "victor"}})

    await users.button_admin_revoke(update, context)

    assert 7 not in context.bot_data["troubleshooter_admins"]
    assert (notes == [{"action": "admin_revoked", "target_id": 7}]) is notified


@pytest.mark.asyncio
async def test_revoke_admin_rejects_non_owner(monkeypatch):
    async def fail_remove(target_id):
        raise AssertionError("non-owner must not revoke")

    monkeypatch.setattr(users, "admin_remove", fail_remove)
    update, calls = make_update("troubleshooter:admin_revoke:7", user_id=OTHER)
    context, _ = make_context(bot_data={"troubleshooter_admins": {7: "victor"}})

    await users.button_admin_revoke(update, context)

    assert 7 in context.bot_data["troubleshooter_admins"]
    assert "Unauthorized" in calls["answers"][0]


@pytest.mark.asyncio
async def test_approve_admin_adds_and_messages_target(monkeypatch):
    added = []

    async def fake_add(user_id, username=None):
        added.append((user_id, username))
        return True

    monkeypatch.setattr(users, "admin_add", fake_add)
    update, calls = make_update("admin:approve:9")
    context, _ = make_context(bot_data={"pending_admin_requests": {9: "@new_bie"}})
    sent = add_send_recorder(context)

    await users.button_admin_approve(update, context)

    assert added == [(9, "new_bie")]
    assert context.bot_data["troubleshooter_admins"] == {9: "@new_bie"}
    assert context.bot_data["pending_admin_requests"] == {}
    assert "Approved @new\\_bie" in calls["edits"][0]["text"]
    assert [s["chat_id"] for s in sent] == [9]


@pytest.mark.asyncio
async def test_approve_admin_without_pending_looks_up_name(monkeypatch):
    added = []

    async def fake_add(user_id, username=None):
        added.append((user_id, username))
        return True

    async def get_chat(chat_id):
        return SimpleNamespace(username="looked_up", first_name="Lou")

    monkeypatch.setattr(users, "admin_add", fake_add)
    update, _ = make_update("admin:approve:9")
    context, _ = make_context()
    context.bot.get_chat = get_chat
    add_send_recorder(context)

    await users.button_admin_approve(update, context)

    assert added == [(9, "looked_up")]


@pytest.mark.asyncio
async def test_approve_admin_db_failure(monkeypatch):
    async def fake_add(user_id, username=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(users, "admin_add", fake_add)
    update, calls = make_update("admin:approve:9")
    context, _ = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})
    sent = add_send_recorder(context)

    with pytest.raises(RuntimeError, match="offline"):
        await users.button_admin_approve(update, context)

    assert calls["edits"] == []
    assert "troubleshooter_admins" not in context.bot_data
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["button_admin_approve", "button_admin_deny"])
async def test_approve_deny_reject_non_owner(monkeypatch, handler):
    async def fail_add(*args, **kwargs):
        raise AssertionError("non-owner must not approve")

    monkeypatch.setattr(users, "admin_add", fail_add)
    action = "approve" if handler.endswith("approve") else "deny"
    update, calls = make_update(f"admin:{action}:9", user_id=OTHER)
    context, _ = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})
    sent = add_send_recorder(context)

    await getattr(users, handler)(update, context)

    assert calls["edits"] == []
    assert sent == []
    assert context.bot_data["pending_admin_requests"] == {9: "@newbie"}


@pytest.mark.asyncio
async def test_deny_admin_clears_request_and_tells_user():
    update, calls = make_update("admin:deny:9")
    context, _ = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})
    sent = add_send_recorder(context)

    await users.button_admin_deny(update, context)

    assert context.bot_data["pending_admin_requests"] == {}
    assert "Denied" in calls["edits"][0]["text"]
    assert [s["chat_id"] for s in sent] == [9]
    assert "declined" in sent[0]["text"]


def users_list_context(codes=(), parts=()):
    context, _ = make_context(
        bot_data={"codes": {c["code"]: c for c in codes}, "parts": list(parts)}
    )
    return context


@pytest.fixture
def registered(monkeypatch):
    rows = [
        {"user_id": 1, "username": "alice", "is_admin": 1, "last_login": None},
        {"user_id": 2, "username": "bob", "is_admin": 0, "last_login": None},
        {"user_id": 3, "username": None, "is_admin": 0, "last_login": None},
    ]

    async def fake_users_get():
        return [dict(r) for r in rows]

    monkeypatch.setattr(users, "users_get", fake_users_get)
    return rows


def user_line(text, name):
    return next(line for line in text.split("\n") if name in line)


@pytest.mark.asyncio
async def test_users_list_counts_codes_and_parts(registered):
    codes = [
        {"code": "E1", "added_by": "@alice", "edits": [{"by": "@bob"}]},
        {"code": "E2", "added_by": "@alice", "edits": []},
    ]
    parts = [
        {"part_no": "PN1", "added_by": "@bob", "edits": [{"by": "@alice"}]},
        {"part_no": "PN2", "added_by": None, "edits": [{"by": "@bob"}]},
        {"part_no": "PN3"},
    ]
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, users_list_context(codes, parts))

    text = calls["edits"][0]["text"]
    assert "➕ 2 · ✏️ 1" in user_line(text, "alice")
    assert "➕ 1 · ✏️ 2" in user_line(text, "bob")
    assert "➕" not in user_line(text, "ID 3")


@pytest.mark.asyncio
async def test_users_list_counts_parts_only(registered):
    parts = [{"part_no": "PN1", "added_by": "@bob", "edits": []}]
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, users_list_context(parts=parts))

    assert "➕ 1 · ✏️ 0" in user_line(calls["edits"][0]["text"], "bob")


@pytest.mark.asyncio
async def test_users_list_sort_by_added_includes_parts(registered):
    codes = [{"code": "E1", "added_by": "@alice"}]
    parts = [
        {"part_no": "PN1", "added_by": "@bob"},
        {"part_no": "PN2", "added_by": "@bob"},
    ]
    update, calls = make_update("troubleshooter:user_list:added")

    await users.button_users_list(update, users_list_context(codes, parts))

    text = calls["edits"][0]["text"]
    assert text.index("bob") < text.index("alice")


@pytest.mark.asyncio
async def test_users_list_links_every_user_by_id(monkeypatch):
    async def fake_users_get():
        return [
            {
                "user_id": 1,
                "username": "Jack_Profits1",
                "is_admin": 0,
                "last_login": None,
            },
            {
                "user_id": 2,
                "username": "Alex <Ford> & Co",
                "is_admin": 0,
                "last_login": None,
            },
            {"user_id": 3, "username": None, "is_admin": 0, "last_login": None},
        ]

    monkeypatch.setattr(users, "users_get", fake_users_get)
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, users_list_context())

    edit = calls["edits"][0]
    assert edit["parse_mode"] == "HTML"
    text = edit["text"]
    assert text.startswith("👥 <b>Registered Users</b> (Total: 3)")
    assert '<a href="https://t.me/Jack_Profits1">@Jack_Profits1</a>' in text
    assert '<a href="tg://user?id=2">Alex &lt;Ford&gt; &amp; Co</a>' in text
    assert '<a href="tg://user?id=3">ID 3</a>' in text


@pytest.mark.asyncio
async def test_users_list_empty(monkeypatch):
    async def fake_users_get():
        return []

    monkeypatch.setattr(users, "users_get", fake_users_get)
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, users_list_context())

    assert (
        calls["edits"][0]["text"]
        == "👥 <b>Registered Users</b>\n\nNo users registered yet."
    )
