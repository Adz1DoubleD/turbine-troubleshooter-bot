from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.tools as tools
from turbine_troubleshooter.blocks import feedback, handle_block
from turbine_troubleshooter.settings import SETTINGS

ALERTS = -100


@pytest.fixture
def alerts(monkeypatch):
    sent = []

    async def send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(SETTINGS, "alerts_chat_id", ALERTS)
    monkeypatch.setattr(SETTINGS, "owner_id", "1")
    monkeypatch.setattr(
        turbine_troubleshooter,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=send_message)),
    )
    users = AsyncMock(return_value=[])
    monkeypatch.setattr(tools, "users_get", users)
    return sent


def typed(text, state="troubleshooter:feedback", username="jsmith"):
    message = SimpleNamespace(text=text, delete=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=42, username=username, full_name="Jane Smith"
        ),
        effective_chat=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock()),
        bot_data={"is_troubleshooter": True},
        user_data={"state": state, "last_msg_id": 7, "is_admin": False},
    )
    return update, context


def labels(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [True, False], ids=["own-bot", "host-bot"])
async def test_feedback_is_only_in_the_troubleshooter_bot(own):
    context = SimpleNamespace(
        bot_data={"is_troubleshooter": own}, user_data={"is_admin": False}
    )

    block = await handle_block(context)

    shown = ("💬 Feedback", "troubleshooter:feedback") in labels(block["reply_markup"])
    assert shown is own


@pytest.mark.asyncio
async def test_button_asks_for_the_message():
    query = SimpleNamespace(
        data="troubleshooter:feedback",
        message=SimpleNamespace(message_id=9),
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    context = SimpleNamespace(
        bot_data={"is_troubleshooter": True},
        user_data={"is_admin": False, "is_approved": True},
    )

    await turbine_troubleshooter.handle_button(
        SimpleNamespace(callback_query=query), context
    )

    assert context.user_data["state"] == "troubleshooter:feedback"
    assert context.user_data["last_msg_id"] == 9
    text = query.edit_message_text.await_args.args[0]
    assert "What would you like to tell the admins?" in text
    assert labels(query.edit_message_text.await_args.kwargs["reply_markup"]) == [
        ("🔙 Cancel", "troubleshooter:home")
    ]


@pytest.mark.asyncio
async def test_message_goes_to_the_alerts_chat_only(alerts):
    update, context = typed("Code 1234_A advice is *old*")

    await turbine_troubleshooter.handle_text_input(update, context)

    assert len(alerts) == 1
    chat_id, text, kwargs = alerts[0]
    assert chat_id == ALERTS
    assert text == (
        "💬 *Feedback*\n\nCode 1234\\_A advice is \\*old\\*\n\n"
        "• From: @jsmith (ID `42`)"
    )
    assert kwargs["parse_mode"] == "Markdown"
    tools.users_get.assert_not_awaited()
    assert context.user_data["state"] is None
    edit = context.bot.edit_message_text.await_args.kwargs
    assert edit["message_id"] == 7
    assert edit["text"] == "✅ Thanks, sent to the admins."
    assert labels(edit["reply_markup"]) == [("🔙 Back", "troubleshooter:home")]


@pytest.mark.asyncio
async def test_name_is_used_without_a_username(alerts):
    update, context = typed("hello", username=None)

    await turbine_troubleshooter.handle_text_input(update, context)

    assert alerts[0][1].endswith("• From: Jane Smith (ID `42`)")


@pytest.mark.asyncio
async def test_long_messages_are_cut_to_the_limit(alerts):
    update, context = typed("x" * 1500)

    await turbine_troubleshooter.handle_text_input(update, context)

    assert "x" * feedback.MAX_FEEDBACK + "\n" in alerts[0][1]
    assert "x" * (feedback.MAX_FEEDBACK + 1) not in alerts[0][1]


@pytest.mark.asyncio
async def test_empty_message_sends_nothing(alerts):
    update, context = typed("   ")

    await turbine_troubleshooter.handle_text_input(update, context)

    assert alerts == []
    assert context.bot.edit_message_text.await_args.kwargs["text"].startswith(
        "⚠️ Nothing was sent."
    )


@pytest.mark.asyncio
async def test_failed_send_tells_the_user_and_reports_it(monkeypatch):
    monkeypatch.setattr(
        feedback,
        "send_notification_troubleshooter",
        AsyncMock(side_effect=RuntimeError("chat not found")),
    )
    reported = MagicMock()
    monkeypatch.setattr(feedback.sentry_sdk, "capture_exception", reported)
    update, context = typed("hello")

    await turbine_troubleshooter.handle_text_input(update, context)

    reported.assert_called_once()
    assert context.bot.edit_message_text.await_args.kwargs["text"] == (
        "⚠️ Couldn't send it just now. Please try again later."
    )


@pytest.mark.asyncio
async def test_new_message_when_the_prompt_is_gone(alerts):
    update, context = typed("hello")
    context.bot.edit_message_text.side_effect = RuntimeError("message gone")

    await turbine_troubleshooter.handle_text_input(update, context)

    context.bot.send_message.assert_awaited_once()
    assert context.bot.send_message.await_args.kwargs["text"] == (
        "✅ Thanks, sent to the admins."
    )


@pytest.mark.asyncio
async def test_text_without_the_feedback_state_is_not_sent(alerts):
    update, context = typed("hello", state=None)

    await turbine_troubleshooter.handle_text_input(update, context)

    assert alerts == []
