from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks.admin import broadcast
from turbine_troubleshooter.settings import SETTINGS

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


def labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_broadcast_rejects_non_owner():
    update, calls = make_update("troubleshooter:broadcast:all", user_id=OTHER)
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    assert calls["edits"] == []
    assert "Unauthorized" in calls["answers"][0]
    assert "state" not in context.user_data


@pytest.mark.asyncio
async def test_broadcast_menu_shows_audience_options():
    update, calls = make_update("troubleshooter:broadcast")
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    cbs = callbacks(calls["edits"][0]["reply_markup"])
    assert cbs == [
        "troubleshooter:broadcast:all",
        "troubleshooter:broadcast:admins",
        "troubleshooter:broadcast:choose",
        "troubleshooter:admin_menu",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choice,audience,label",
    [("all", "all", "all registered users"), ("admins", "admins", "all admins")],
)
async def test_broadcast_choice_sets_state_and_audience(choice, audience, label):
    update, calls = make_update(f"troubleshooter:broadcast:{choice}")
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    assert context.user_data["state"] == "troubleshooter:broadcast"
    assert context.user_data["broadcast_audience"] == audience
    assert context.user_data["last_msg_id"] == 55
    assert label in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_broadcast_choose_lists_users_with_admin_badge(monkeypatch):
    async def fake_users_get():
        return [
            {"user_id": 1, "username": "alice", "is_admin": 1},
            {"user_id": 4, "username": None, "is_admin": 0},
        ]

    monkeypatch.setattr(broadcast, "users_get", fake_users_get)
    update, calls = make_update("troubleshooter:broadcast:choose")
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    markup = calls["edits"][0]["reply_markup"]
    assert labels(markup)[:2] == ["🛡️ @alice", "4"]
    assert callbacks(markup)[:2] == [
        "troubleshooter:broadcast:user:1",
        "troubleshooter:broadcast:user:4",
    ]
    assert "state" not in context.user_data


@pytest.mark.asyncio
async def test_broadcast_single_user_sets_int_audience(monkeypatch):
    async def fake_user_get(user_id):
        assert user_id == 4
        return {"user_id": 4, "username": "bob_smith", "is_admin": 0}

    monkeypatch.setattr(broadcast, "user_get", fake_user_get)
    update, calls = make_update("troubleshooter:broadcast:user:4")
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    assert context.user_data["broadcast_audience"] == 4
    assert "@bob\\_smith" in calls["edits"][0]["text"]


@pytest.mark.asyncio
async def test_handle_broadcast_sends_with_audience_and_shows_summary(monkeypatch):
    sent = []

    async def fake_notify(**kwargs):
        sent.append(kwargs)
        return 2, 1, ["@alice", "@carol"]

    monkeypatch.setattr(broadcast, "send_notification_troubleshooter", fake_notify)
    update, calls = make_update(user_id=OWNER, with_query=False)
    context, bot_edits = make_context(
        user_data={
            "state": "troubleshooter:broadcast",
            "broadcast_audience": "admins",
            "last_msg_id": 55,
        }
    )

    await broadcast.handle_broadcast(update, context, "Hello all")

    assert sent == [
        {"action": "broadcast", "message": "Hello all", "audience": "admins"}
    ]
    assert context.user_data["state"] is None
    assert "broadcast_audience" not in context.user_data
    assert calls["deleted"] is True

    summary = bot_edits[0]["text"]
    assert "Broadcast Complete" in summary
    assert "`2`" in summary and "`1`" in summary
    assert "@alice, @carol" in summary


@pytest.mark.asyncio
async def test_handle_broadcast_ignores_non_owner(monkeypatch):
    async def fail_notify(**kwargs):
        raise AssertionError("non-owner must not broadcast")

    monkeypatch.setattr(broadcast, "send_notification_troubleshooter", fail_notify)
    update, _ = make_update(user_id=OTHER, with_query=False)
    context, bot_edits = make_context(user_data={"state": "troubleshooter:broadcast"})

    await broadcast.handle_broadcast(update, context, "sneaky")

    assert bot_edits == []


@pytest.mark.asyncio
async def test_broadcast_choose_pages_users(monkeypatch):
    async def fake_users_get():
        return [
            {"user_id": i, "username": f"u{i:02}", "is_admin": 0} for i in range(45)
        ]

    monkeypatch.setattr(broadcast, "users_get", fake_users_get)
    update, calls = make_update("troubleshooter:broadcast:choose:2")
    context, _ = make_context()

    await broadcast.button_broadcast(update, context)

    edit = calls["edits"][0]
    picks = [c for c in callbacks(edit["reply_markup"]) if ":user:" in c]
    assert picks == [f"troubleshooter:broadcast:user:{i}" for i in range(40, 45)]
    assert "Page 3 of 3" in edit["text"]
    assert "troubleshooter:broadcast:choose:1" in callbacks(edit["reply_markup"])
