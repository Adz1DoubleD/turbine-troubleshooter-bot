from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks import user
from turbine_troubleshooter.settings import SETTINGS


def make_query_update(data, user_id=123, username="tester"):
    calls = {"edits": [], "answers": [], "markups": []}

    async def edit_message_text(text, **kwargs):
        calls["edits"].append({"text": text, **kwargs})

    async def edit_message_reply_markup(reply_markup=None):
        calls["markups"].append(reply_markup)

    async def answer(text=None, **kwargs):
        calls["answers"].append(text)

    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username=username, full_name="Test User"),
        message=SimpleNamespace(message_id=55),
        edit_message_text=edit_message_text,
        edit_message_reply_markup=edit_message_reply_markup,
        answer=answer,
    )
    return SimpleNamespace(callback_query=query), calls


def bot_recorder():
    record = {"sent": [], "edits": []}

    async def send_message(chat_id=None, text=None, **kwargs):
        record["sent"].append({"chat_id": chat_id, "text": text, **kwargs})

    async def edit_message_text(**kwargs):
        record["edits"].append(kwargs)

    bot = SimpleNamespace(
        send_message=send_message, edit_message_text=edit_message_text
    )
    return bot, record


def button_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,status,button",
    [
        (1, "🔔 *On*", "🔕 Turn Off Notifications"),
        (0, "🔕 *Off*", "🔔 Turn On Notifications"),
    ],
)
async def test_user_menu_shows_current_state(monkeypatch, enabled, status, button):
    async def fake_get(user_id):
        assert user_id == 123
        return enabled

    monkeypatch.setattr(user, "user_notifications_get", fake_get)

    update, calls = make_query_update("troubleshooter:user_menu")
    context = SimpleNamespace(user_data={"state": "previous"}, bot_data={})
    await user.button_menu(update, context)

    assert context.user_data["state"] is None
    assert status in calls["edits"][0]["text"]
    labels = button_labels(calls["edits"][0]["reply_markup"])
    assert button in labels
    assert not any("Feedback" in label or "Suggest" in label for label in labels)


@pytest.mark.asyncio
async def test_user_menu_toggle_flips_and_shows_new_state(monkeypatch):
    toggled = []

    async def fake_toggle(user_id):
        toggled.append(user_id)
        return 0

    async def fail_get(user_id):
        raise AssertionError("toggle path shouldn't call get")

    monkeypatch.setattr(user, "user_notifications_toggle", fake_toggle)
    monkeypatch.setattr(user, "user_notifications_get", fail_get)

    update, calls = make_query_update("troubleshooter:notifications:toggle")
    context = SimpleNamespace(user_data={}, bot_data={})
    await user.button_menu(update, context)

    assert toggled == [123]
    assert "🔕 *Off*" in calls["edits"][0]["text"]
    assert "🔔 Turn On Notifications" in button_labels(
        calls["edits"][0]["reply_markup"]
    )


@pytest.mark.asyncio
async def test_user_menu_db_error_propagates(monkeypatch):
    async def broken_get(user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(user, "user_notifications_get", broken_get)

    update, calls = make_query_update("troubleshooter:user_menu")
    context = SimpleNamespace(user_data={}, bot_data={})
    with pytest.raises(RuntimeError, match="db down"):
        await user.button_menu(update, context)

    assert calls["edits"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "new_state,toast", [(0, "🔕 Notifications off"), (1, "🔔 Notifications on")]
)
async def test_alert_toggle_updates_buttons(monkeypatch, new_state, toast):
    toggled = []

    async def fake_toggle(user_id):
        toggled.append(user_id)
        return new_state

    monkeypatch.setattr(user, "user_notifications_toggle", fake_toggle)
    update, calls = make_query_update("troubleshooter:notifications:alert")

    await user.button_alert_toggle(update, SimpleNamespace(bot_data={}, user_data={}))

    assert toggled == [123]
    assert calls["answers"] == [toast]
    assert (
        calls["markups"][0].inline_keyboard[0][0].callback_data
        == "troubleshooter:notifications:alert"
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_request_admin_sends_request_to_alerts(monkeypatch):
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", -100)
    bot, record = bot_recorder()
    update, calls = make_query_update("admin:request")
    context = SimpleNamespace(
        bot=bot, user_data={"is_admin": False}, bot_data={"is_troubleshooter": True}
    )

    await user.button_request_admin(update, context)

    assert context.bot_data["pending_admin_requests"] == {123: "@tester"}
    assert record["sent"][0]["chat_id"] == -100
    assert callbacks(record["sent"][0]["reply_markup"]) == [
        "admin:deny:123",
        "admin:approve:123",
    ]
    assert "sent" in calls["answers"][0]


@pytest.mark.asyncio
async def test_request_admin_already_waiting():
    bot, record = bot_recorder()
    update, calls = make_query_update("admin:request")
    context = SimpleNamespace(
        bot=bot,
        user_data={"is_admin": False},
        bot_data={
            "is_troubleshooter": True,
            "pending_admin_requests": {123: "@tester"},
        },
    )

    await user.button_request_admin(update, context)

    assert record["sent"] == []
    assert "already waiting" in calls["answers"][0]


@pytest.mark.asyncio
async def test_request_admin_when_already_admin_shows_menu():
    bot, record = bot_recorder()
    update, calls = make_query_update("admin:request")
    context = SimpleNamespace(
        bot=bot,
        user_data={"is_admin": True},
        bot_data={"is_troubleshooter": True, "codes": {}, "parts": []},
    )

    await user.button_request_admin(update, context)

    assert record["sent"] == []
    assert "already have admin" in calls["answers"][0]
    assert "Acme Troubleshooter Bot" in calls["edits"][0]["text"]
