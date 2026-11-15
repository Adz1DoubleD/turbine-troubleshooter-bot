from types import SimpleNamespace

import pytest

from troubleshooter.blocks import wtg


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def wtg_context():
    edits = []

    async def edit_message_text(**kwargs):
        edits.append(kwargs)

    context = SimpleNamespace(
        bot=SimpleNamespace(edit_message_text=edit_message_text),
        user_data={"state": "troubleshooter:wtg_search", "last_msg_id": 9},
        bot_data={},
    )
    return context, edits


UPDATE = SimpleNamespace(effective_chat=SimpleNamespace(id=1))


@pytest.mark.asyncio
async def test_button_search_sets_state():
    edits = []

    async def edit_message_text(text, **kwargs):
        edits.append(text)

    query = SimpleNamespace(
        message=SimpleNamespace(message_id=55), edit_message_text=edit_message_text
    )
    context = SimpleNamespace(user_data={}, bot_data={})

    await wtg.button_search(SimpleNamespace(callback_query=query), context)

    assert context.user_data["state"] == "troubleshooter:wtg_search"
    assert context.user_data["last_msg_id"] == 55
    assert "WTG Info Lookup" in edits[0]


@pytest.mark.asyncio
async def test_handle_search_found_shows_serial_and_ip(monkeypatch):
    looked_up = []

    def fake_find(text):
        looked_up.append(text)
        return "WTA10", {"serial": 1000001, "ip": "192.0.2.10"}

    monkeypatch.setattr(wtg, "find_wtg", fake_find)
    context, edits = wtg_context()

    await wtg.handle_search(UPDATE, context, "a10")

    assert looked_up == ["a10"]
    assert context.user_data["state"] is None
    assert edits[0]["message_id"] == 9
    assert "WTA10" in edits[0]["text"]
    assert "`1000001`" in edits[0]["text"]
    assert "`192.0.2.10`" in edits[0]["text"]
    assert callbacks(edits[0]["reply_markup"]) == [
        "troubleshooter:wtg_search",
        "back:troubleshooter",
    ]


@pytest.mark.asyncio
async def test_handle_search_not_found_cleans_input(monkeypatch):
    monkeypatch.setattr(wtg, "find_wtg", lambda text: (None, None))
    context, edits = wtg_context()

    await wtg.handle_search(UPDATE, context, "`" + "Z" * 30)

    assert "WTG Not Found" in edits[0]["text"]
    assert "`" + "Z" * 20 + "`" in edits[0]["text"]
    assert "Z" * 21 not in edits[0]["text"]


@pytest.mark.asyncio
async def test_handle_search_known_format_but_no_data(monkeypatch):
    monkeypatch.setattr(wtg, "find_wtg", lambda text: ("WTZ99", None))
    context, edits = wtg_context()

    await wtg.handle_search(UPDATE, context, "Z99")

    assert "WTG Not Found" in edits[0]["text"]
    assert "`Z99`" in edits[0]["text"]
