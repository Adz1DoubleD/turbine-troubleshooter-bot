import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update
from telegram.error import BadRequest

import turbine_troubleshooter.helpers as helpers
from turbine_troubleshooter.settings import SETTINGS


def crashed_update(error):
    update = MagicMock(spec=Update)
    update.edited_message = None
    update.effective_message.reply_text = AsyncMock()
    return update, SimpleNamespace(error=error, bot_data={})


@pytest.fixture
def reported(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(helpers.sentry_sdk, "capture_exception", mock)
    monkeypatch.setattr(helpers, "is_local", lambda: False)
    return mock


@pytest.mark.asyncio
async def test_error_reply_hides_details_and_reports(reported):
    error = RuntimeError("Can't connect to MySQL server on 'db.host'")
    update, context = crashed_update(error)

    await helpers.error_handler(update, context)

    reply = update.effective_message.reply_text.await_args.args[0]
    assert reply == helpers.ERROR_REPLY
    reported.assert_called_once_with(error)


@pytest.mark.asyncio
async def test_noise_errors_are_ignored(reported):
    update, context = crashed_update(RuntimeError("Query is too old"))

    await helpers.error_handler(update, context)

    update.effective_message.reply_text.assert_not_awaited()
    reported.assert_not_called()


@pytest.mark.asyncio
async def test_edited_messages_are_ignored(reported):
    update, context = crashed_update(RuntimeError("boom"))
    update.edited_message = object()

    await helpers.error_handler(update, context)

    update.effective_message.reply_text.assert_not_awaited()
    reported.assert_not_called()


def test_noise_filter():
    noisy = logging.LogRecord("x", logging.ERROR, "", 0, "Query is too old", (), None)
    real = logging.LogRecord("x", logging.ERROR, "", 0, "real problem", (), None)

    assert helpers.error_handler_noise_filter(noisy) is False
    assert helpers.error_handler_noise_filter(real) is True


@pytest.mark.parametrize(
    "chat_id, user_id, expected",
    [("42", 42, True), ("42", "42", True), ("42", 7, False), (None, 42, False)],
)
def test_is_owner(monkeypatch, chat_id, user_id, expected):
    monkeypatch.setattr(SETTINGS, "owner_id", chat_id)

    assert helpers.is_owner(user_id) is expected


def test_escape_markdown():
    assert helpers.escape_markdown("a_b*c[d`e") == r"a\_b\*c\[d\`e"


@pytest.mark.asyncio
async def test_close_message_fallback_reopens_troubleshooter():
    query = SimpleNamespace(
        message=SimpleNamespace(
            delete=AsyncMock(side_effect=BadRequest("can't delete")), text="hi"
        ),
        edit_message_text=AsyncMock(),
    )

    await helpers.close_message(query)

    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "troubleshooter:home"
