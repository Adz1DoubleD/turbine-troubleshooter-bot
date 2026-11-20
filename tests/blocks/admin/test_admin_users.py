from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks.admin import changes, users
from turbine_troubleshooter.settings import SETTINGS

OWNER = 123
OTHER = 456


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


@pytest.fixture(autouse=True)
def db(monkeypatch):
    calls = []

    def fake(name):
        async def call(*args):
            calls.append((name, *args))
            return True

        monkeypatch.setattr(users, name, call)

    for name in (
        "admin_add",
        "admin_remove",
        "user_approve",
        "user_revoke",
        "request_remove",
    ):
        fake(name)
    return calls


@pytest.fixture
def notes(monkeypatch):
    sent = []

    async def fake_notify(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(users, "send_notification_troubleshooter", fake_notify)
    return sent


def make_update(data=None, user_id=OWNER):
    calls = {"answers": [], "edits": []}

    async def answer(text=None, **kwargs):
        calls["answers"].append(text)

    async def edit_message_text(text=None, **kwargs):
        calls["edits"].append({"text": text, **kwargs})

    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        answer=answer,
        edit_message_text=edit_message_text,
    )
    return SimpleNamespace(callback_query=query), calls


def make_context(is_admin=True, bot_data=None):
    sent = []

    async def send_message(chat_id, text=None, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})

    return SimpleNamespace(
        user_data={"is_admin": is_admin},
        bot_data=bot_data if bot_data is not None else {},
        bot=SimpleNamespace(send_message=send_message, sent=sent),
    )


def callbacks(edit):
    return [
        b.callback_data for row in edit["reply_markup"].inline_keyboard for b in row
    ]


def labels(edit):
    return [b.text for row in edit["reply_markup"].inline_keyboard for b in row]


# --- Approve / Deny from the alerts chat ------------------------------------


@pytest.mark.asyncio
async def test_approve_admin_adds_and_messages_target(db):
    update, calls = make_update("troubleshooter:admin:approve:9")
    context = make_context(bot_data={"pending_admin_requests": {9: "@new_bie"}})

    await users.button_admin_approve(update, context)

    assert ("admin_add", 9, "new_bie") in db
    assert ("request_remove", 9) in db
    assert context.bot_data["troubleshooter_admins"] == {9: "@new_bie"}
    assert context.bot_data["pending_admin_requests"] == {}
    assert "Approved @new\\_bie" in calls["edits"][0]["text"]
    assert [s["chat_id"] for s in context.bot.sent] == [9]


@pytest.mark.asyncio
async def test_approve_admin_without_pending_looks_up_name(db):
    async def get_chat(chat_id):
        return SimpleNamespace(username="looked_up", first_name="Lou")

    update, _ = make_update("troubleshooter:admin:approve:9")
    context = make_context()
    context.bot.get_chat = get_chat

    await users.button_admin_approve(update, context)

    assert ("admin_add", 9, "looked_up") in db


@pytest.mark.asyncio
async def test_approve_admin_db_failure(monkeypatch):
    async def fake_add(user_id, username=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(users, "admin_add", fake_add)
    update, calls = make_update("troubleshooter:admin:approve:9")
    context = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})

    with pytest.raises(RuntimeError, match="offline"):
        await users.button_admin_approve(update, context)

    assert calls["edits"] == []
    assert "troubleshooter_admins" not in context.bot_data
    assert context.bot.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["button_admin_approve", "button_admin_deny"])
async def test_approve_deny_reject_non_owner(db, handler):
    action = "approve" if handler.endswith("approve") else "deny"
    update, calls = make_update(f"admin:{action}:9", user_id=OTHER)
    context = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})

    await getattr(users, handler)(update, context)

    assert db == []
    assert calls["edits"] == []
    assert context.bot.sent == []
    assert context.bot_data["pending_admin_requests"] == {9: "@newbie"}


@pytest.mark.asyncio
async def test_deny_admin_clears_request_and_tells_user(db):
    update, calls = make_update("troubleshooter:admin:deny:9")
    context = make_context(bot_data={"pending_admin_requests": {9: "@newbie"}})

    await users.button_admin_deny(update, context)

    assert context.bot_data["pending_admin_requests"] == {}
    assert ("request_remove", 9) in db
    assert "Denied" in calls["edits"][0]["text"]
    assert [s["chat_id"] for s in context.bot.sent] == [9]
    assert "declined" in context.bot.sent[0]["text"]


# --- Users list -------------------------------------------------------------

ROWS = [
    {"user_id": 1, "username": "alice", "last_login": None},
    {"user_id": 2, "username": "bob", "last_login": None},
    {"user_id": 3, "username": None, "last_login": None},
    {"user_id": OWNER, "username": "boss", "last_login": None},
]


def serve_users(monkeypatch, rows):
    async def fake_users_get():
        return [dict(r) for r in rows]

    async def fake_user_get(user_id):
        return next((dict(r) for r in rows if r["user_id"] == user_id), None)

    monkeypatch.setattr(users, "users_get", fake_users_get)
    monkeypatch.setattr(users, "user_get", fake_user_get)


@pytest.fixture
def registered(monkeypatch):
    serve_users(monkeypatch, ROWS)


def roles_context(codes=(), parts=(), pending=None, is_admin=True):
    return make_context(
        is_admin=is_admin,
        bot_data={
            "codes": {c["code"]: c for c in codes},
            "parts": list(parts),
            "troubleshooter_admins": {1: "@alice"},
            "troubleshooter_approved": {1, 2},
            "pending_access_requests": dict(pending or {}),
            "pending_admin_requests": {},
        },
    )


@pytest.mark.asyncio
async def test_users_list_shows_badges_and_stats(registered):
    codes = [
        {"code": "E1", "added_by": "@alice", "edits": [{"by": "@bob"}]},
        {"code": "E2", "added_by": "@alice", "edits": []},
    ]
    parts = [{"part_no": "PN1", "added_by": "@bob", "edits": [{"by": "@alice"}]}]
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, roles_context(codes, parts))

    edit = calls["edits"][0]
    assert edit["parse_mode"] == "HTML"
    assert edit["text"].startswith("👥 <b>Users</b> (4)")
    shown = labels(edit)
    assert "🛡️ @alice · ➕2 ✏️1" in shown
    assert "✅ @bob · ➕1 ✏️1" in shown
    assert "🔒 ID 3" in shown
    assert "👑 @boss" in shown
    assert "troubleshooter:user:2" in callbacks(edit)
    assert "troubleshooter:export:users" not in callbacks(edit)


@pytest.mark.asyncio
async def test_users_list_sort_by_added(registered):
    codes = [{"code": "E1", "added_by": "@alice"}]
    parts = [
        {"part_no": "PN1", "added_by": "@bob"},
        {"part_no": "PN2", "added_by": "@bob"},
    ]
    update, calls = make_update("troubleshooter:user_list:added:0")

    await users.button_users_list(update, roles_context(codes, parts))

    shown = labels(calls["edits"][0])
    assert shown.index("✅ @bob · ➕2 ✏️0") < shown.index("🛡️ @alice · ➕1 ✏️0")
    assert "• ➕ Added •" in shown


@pytest.mark.asyncio
async def test_users_list_pages_and_remembers_place(monkeypatch):
    rows = [
        {"user_id": i, "username": f"u{i:02}", "last_login": None} for i in range(25)
    ]

    async def fake_users_get():
        return [dict(r) for r in rows]

    monkeypatch.setattr(users, "users_get", fake_users_get)
    context = roles_context()
    update, calls = make_update("troubleshooter:user_list:name:2")

    await users.button_users_list(update, context)

    edit = calls["edits"][0]
    assert "Page 3 of 3" in edit["text"]
    user_buttons = [c for c in callbacks(edit) if c.startswith("troubleshooter:user:")]
    assert len(user_buttons) == 5
    assert "troubleshooter:user_list:name:1" in callbacks(edit)
    assert context.user_data["user_list"] == ("name", 2)
    assert users._users_back(context) == "troubleshooter:user_list:name:2"


@pytest.mark.asyncio
async def test_users_list_empty(monkeypatch):
    async def fake_users_get():
        return []

    monkeypatch.setattr(users, "users_get", fake_users_get)
    update, calls = make_update("troubleshooter:user_list")

    await users.button_users_list(update, roles_context())

    assert "No users registered yet." in calls["edits"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,shown", [(OWNER, True), (OTHER, False)])
async def test_users_list_pending_button_owner_only(registered, user_id, shown):
    update, calls = make_update("troubleshooter:user_list", user_id=user_id)

    await users.button_users_list(update, roles_context(pending={3: "@new"}))

    assert ("troubleshooter:pending" in callbacks(calls["edits"][0])) is shown


@pytest.mark.asyncio
async def test_users_list_rejects_non_admin(registered):
    update, calls = make_update("troubleshooter:user_list", user_id=OTHER)

    await users.button_users_list(update, roles_context(is_admin=False))

    assert calls["edits"] == []
    assert "Unauthorized" in calls["answers"][0]


# --- User card and actions --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id,actions",
    [
        (1, ["admin_remove", "access_remove"]),
        (2, ["admin_add", "access_remove"]),
        (3, ["access_add"]),
        (OWNER, []),
    ],
)
async def test_card_actions_follow_role(registered, user_id, actions):
    update, calls = make_update(f"troubleshooter:user:{user_id}")

    await users.button_user_card(update, roles_context())

    shown = [
        c.split(":")[2]
        for c in callbacks(calls["edits"][0])
        if c.startswith("troubleshooter:user_act:")
    ]
    assert shown == actions


@pytest.mark.asyncio
async def test_card_shows_details_but_no_actions_to_admin(registered):
    codes = [{"code": "E1", "added_by": "@bob", "edits": []}]
    update, calls = make_update("troubleshooter:user:2", user_id=OTHER)

    await users.button_user_card(update, roles_context(codes, pending={2: "@bob"}))

    edit = calls["edits"][0]
    assert '<a href="https://t.me/bob">@bob</a>' in edit["text"]
    assert "Role: Approved user" in edit["text"]
    assert "Added: 1" in edit["text"]
    assert "Has asked for access" in edit["text"]
    assert callbacks(edit) == ["troubleshooter:user_list:name:0"]


@pytest.mark.asyncio
async def test_card_escapes_names_and_links_by_id(monkeypatch):
    serve_users(
        monkeypatch,
        [{"user_id": 2, "username": "Alex <Ford> & Co", "last_login": None}],
    )
    update, calls = make_update("troubleshooter:user:2")

    await users.button_user_card(update, roles_context())

    assert (
        '<a href="tg://user?id=2">Alex &lt;Ford&gt; &amp; Co</a>'
        in (calls["edits"][0]["text"])
    )


@pytest.mark.asyncio
async def test_action_asks_for_confirmation_first(registered, db):
    update, calls = make_update("troubleshooter:user_act:access_remove:2")

    await users.button_user_action(update, roles_context())

    edit = calls["edits"][0]
    assert "Remove <b>@bob</b>'s access?" in edit["text"]
    assert callbacks(edit) == [
        "troubleshooter:user_do:access_remove:2",
        "troubleshooter:user:2",
    ]
    assert db == []


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["button_user_action", "button_user_do"])
async def test_actions_owner_only(registered, db, handler):
    update, calls = make_update("troubleshooter:user_do:access_remove:2", OTHER)
    context = roles_context()

    await getattr(users, handler)(update, context)

    assert db == []
    assert calls["edits"] == []
    assert "owner" in calls["answers"][0]
    assert 2 in context.bot_data["troubleshooter_approved"]


@pytest.mark.asyncio
async def test_remove_access_locks_out_and_tells_user(registered, db, notes):
    update, calls = make_update("troubleshooter:user_do:access_remove:2")
    context = roles_context()

    await users.button_user_do(update, context)

    assert ("user_revoke", 2) in db
    assert 2 not in context.bot_data["troubleshooter_approved"]
    assert notes == [{"action": "access_revoked", "target_id": 2}]
    assert calls["edits"][0]["text"].startswith("✅ Access removed.")


@pytest.mark.asyncio
async def test_remove_access_from_admin_drops_admin_too(registered, db, notes):
    update, _ = make_update("troubleshooter:user_do:access_remove:1")
    context = roles_context()

    await users.button_user_do(update, context)

    assert ("admin_remove", 1) in db
    assert 1 not in context.bot_data["troubleshooter_admins"]
    assert 1 not in context.bot_data["troubleshooter_approved"]


@pytest.mark.asyncio
@pytest.mark.parametrize("removed,notified", [(True, True), (False, False)])
async def test_remove_admin_keeps_access(
    monkeypatch, registered, db, notes, removed, notified
):
    async def fake_remove(user_id):
        db.append(("admin_remove", user_id))
        return removed

    monkeypatch.setattr(users, "admin_remove", fake_remove)
    update, calls = make_update("troubleshooter:user_do:admin_remove:1")
    context = roles_context()

    await users.button_user_do(update, context)

    assert 1 not in context.bot_data["troubleshooter_admins"]
    assert 1 in context.bot_data["troubleshooter_approved"]
    assert ("user_approve", 1) in db
    assert (notes == [{"action": "admin_revoked", "target_id": 1}]) is notified
    assert "Role: Approved user" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_make_admin_from_card(registered, db):
    update, calls = make_update("troubleshooter:user_do:admin_add:2")
    context = roles_context()

    await users.button_user_do(update, context)

    assert ("admin_add", 2, "bob") in db
    assert context.bot_data["troubleshooter_admins"][2] == "@bob"
    assert [s["chat_id"] for s in context.bot.sent] == [2]
    assert "Role: Admin" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_give_access_from_card_clears_request(registered, db):
    update, _ = make_update("troubleshooter:user_do:access_add:3")
    context = roles_context(pending={3: "@new"})

    await users.button_user_do(update, context)

    assert ("user_approve", 3) in db
    assert ("request_remove", 3) in db
    assert 3 in context.bot_data["troubleshooter_approved"]
    assert context.bot_data["pending_access_requests"] == {}


@pytest.mark.asyncio
async def test_stale_action_does_nothing(registered, db):
    update, calls = make_update("troubleshooter:user_do:admin_add:1")

    await users.button_user_do(update, roles_context())

    assert db == []
    assert calls["edits"][0]["text"].startswith("ℹ️ Nothing to change.")


# --- Pending screen ---------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_screen_lists_requests(registered):
    context = roles_context(pending={3: "@new"})
    context.bot_data["pending_admin_requests"] = {2: "@bob"}
    update, calls = make_update("troubleshooter:pending")

    await changes.button_pending(update, context)

    edit = calls["edits"][0]
    assert "@new wants access" in edit["text"]
    assert "@bob wants admin" in edit["text"]
    assert callbacks(edit) == [
        "troubleshooter:access:approve:3:p",
        "troubleshooter:access:deny:3:p",
        "troubleshooter:admin:approve:2:p",
        "troubleshooter:admin:deny:2:p",
        "troubleshooter:admin_menu",
    ]


@pytest.mark.asyncio
async def test_pending_screen_owner_only(registered):
    update, calls = make_update("troubleshooter:pending", user_id=OTHER)

    await changes.button_pending(update, roles_context(pending={3: "@new"}))

    assert calls["edits"] == []
    assert "owner" in calls["answers"][0]


@pytest.mark.asyncio
async def test_approve_from_pending_returns_to_pending(registered, db):
    context = roles_context(pending={3: "@new"})
    update, calls = make_update("troubleshooter:access:approve:3:p")

    await users.button_access_approve(update, context)

    text = calls["edits"][0]["text"]
    assert text.startswith("✅ Gave @new access.")
    assert "Nothing waiting." in text
    assert ("request_remove", 3) in db


@pytest.mark.asyncio
async def test_deny_from_pending_returns_to_pending(registered, db):
    context = roles_context(pending={3: "@new"})
    update, calls = make_update("troubleshooter:access:deny:3:p")

    await users.button_access_deny(update, context)

    assert calls["edits"][0]["text"].startswith("❌ Denied access for @new.")
    assert context.bot_data["pending_access_requests"] == {}
    assert ("request_remove", 3) in db
    assert "declined" in context.bot.sent[0]["text"]


@pytest.mark.asyncio
async def test_pending_screen_pages(registered):
    context = roles_context(pending={i: f"@p{i}" for i in range(100, 125)})
    update, calls = make_update("troubleshooter:pending:2")

    await changes.button_pending(update, context)

    edit = calls["edits"][0]
    approves = [c for c in callbacks(edit) if ":approve:" in c]
    assert approves == [f"troubleshooter:access:approve:{i}:p" for i in range(120, 125)]
    assert "Page 3 of 3" in edit["text"]
    assert "troubleshooter:pending:1" in callbacks(edit)
    assert context.user_data["pending_page"] == 2


@pytest.mark.asyncio
async def test_approve_from_pending_stays_on_page(registered, db):
    context = roles_context(pending={i: f"@p{i}" for i in range(100, 125)})
    context.user_data["pending_page"] = 1
    update, calls = make_update("troubleshooter:access:approve:110:p")

    await users.button_access_approve(update, context)

    assert "Page 2 of 3" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_search_prompt_waits_for_text(registered):
    context = roles_context()
    update, calls = make_update("troubleshooter:user_search")
    update.callback_query.message = SimpleNamespace(message_id=77)

    await users.button_user_search(update, context)

    assert context.user_data["state"] == "troubleshooter:user_search"
    assert context.user_data["last_msg_id"] == 77
    assert "Find a User" in calls["edits"][0]["text"]


def text_update(user_id=OWNER):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search,found",
    [
        ("BO", ["troubleshooter:user:2", f"troubleshooter:user:{OWNER}"]),
        ("@alice", ["troubleshooter:user:1"]),
        ("3", ["troubleshooter:user:3"]),
        ("zzz", []),
    ],
)
async def test_search_filters_list(registered, search, found):
    context = roles_context()
    context.user_data.update(state="troubleshooter:user_search", last_msg_id=77)
    edits = []

    async def edit_message_text(**kwargs):
        edits.append(kwargs)

    context.bot.edit_message_text = edit_message_text

    await users.handle_user_search(text_update(), context, search)

    edit = edits[0]
    assert edit["message_id"] == 77
    assert context.user_data["state"] is None
    shown = [c for c in callbacks(edit) if c.startswith("troubleshooter:user:")]
    assert shown == found
    assert "✖️ Clear search" in labels(edit)
    if not found:
        assert "No matching users." in edit["text"]


@pytest.mark.asyncio
async def test_search_kept_while_paging_and_cleared_from_panel(registered):
    context = roles_context()
    context.user_data["user_search"] = "bob"

    update, calls = make_update("troubleshooter:user_list:login:0")
    await users.button_users_list(update, context)
    paged = [c for c in callbacks(calls["edits"][0]) if ":user:" in c]

    update, calls = make_update("troubleshooter:user_list")
    await users.button_users_list(update, context)
    fresh = [c for c in callbacks(calls["edits"][0]) if ":user:" in c]

    assert paged == ["troubleshooter:user:2"]
    assert len(fresh) == 4
    assert "user_search" not in context.user_data
