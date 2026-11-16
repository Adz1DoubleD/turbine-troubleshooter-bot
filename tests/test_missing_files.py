from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter


def make_update(data, message_text="menu"):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(
            text=message_text,
            chat_id=42,
            reply_document=AsyncMock(),
            reply_photo=AsyncMock(),
        ),
    )
    return SimpleNamespace(callback_query=query), query


def item(kind, file):
    return {
        "troubleshooter:doc": {
            "type": kind,
            "title": "Manual",
            "content": "",
            "file": file,
            "parent": "troubleshooter:docs",
        }
    }


def context():
    return SimpleNamespace(
        bot_data={}, user_data={}, bot=SimpleNamespace(send_message=AsyncMock())
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "photo"])
async def test_missing_file_shows_unavailable(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(
        turbine_troubleshooter,
        "get_troubleshooter_content",
        lambda: item(kind, tmp_path / "gone.pdf"),
    )
    update, query = make_update("troubleshooter:doc")

    await turbine_troubleshooter.handle_button(update, context())

    text = query.edit_message_text.await_args.args[0]
    assert "isn't available right now" in text
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "troubleshooter:docs"
    query.message.reply_document.assert_not_awaited()
    query.message.reply_photo.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_missing_file_in_a_set_shows_unavailable(monkeypatch, tmp_path):
    present = tmp_path / "here.pdf"
    present.write_bytes(b"x")
    monkeypatch.setattr(
        turbine_troubleshooter,
        "get_troubleshooter_content",
        lambda: item("document", [present, tmp_path / "gone.pdf"]),
    )
    update, query = make_update("troubleshooter:doc")

    await turbine_troubleshooter.handle_button(update, context())

    assert "isn't available" in query.edit_message_text.await_args.args[0]
    query.message.reply_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_file_from_a_photo_message_sends_new_message(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        turbine_troubleshooter,
        "get_troubleshooter_content",
        lambda: item("document", tmp_path / "gone.pdf"),
    )
    close = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "close_message", close)
    update, query = make_update("troubleshooter:doc", message_text=None)
    ctx = context()

    await turbine_troubleshooter.handle_button(update, ctx)

    close.assert_awaited_once()
    assert ctx.bot.send_message.await_args.args[0] == 42
    assert "isn't available" in ctx.bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_present_file_is_sent(monkeypatch, tmp_path):
    present = tmp_path / "here.pdf"
    present.write_bytes(b"x")
    monkeypatch.setattr(
        turbine_troubleshooter,
        "get_troubleshooter_content",
        lambda: item("document", present),
    )
    monkeypatch.setattr(turbine_troubleshooter, "close_message", AsyncMock())
    update, query = make_update("troubleshooter:doc")

    await turbine_troubleshooter.handle_button(update, context())

    assert query.message.reply_document.await_args.kwargs["document"] == Path(present)
