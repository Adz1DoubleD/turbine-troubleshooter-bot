from types import SimpleNamespace

import pytest

import turbine_troubleshooter.blocks as blocks


def button_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


SAMPLE_CONTENT = {
    "troubleshooter:ioboard": {"type": "menu", "title": "IO Boards"},
    "troubleshooter:torque": {
        "type": "menu",
        "title": "Torque",
        "items": ["troubleshooter:torque:hub"],
        "parent": None,
    },
    "troubleshooter:torque:hub": {
        "type": "text",
        "title": "Hub",
        "content": "hub text",
        "file": None,
        "parent": "troubleshooter:torque",
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("is_troubleshooter,shown", [(True, True), (False, False)])
async def test_main_menu_user_buttons_only_in_the_troubleshooter_bot(
    is_troubleshooter, shown
):
    context = SimpleNamespace(
        bot_data={"is_troubleshooter": is_troubleshooter, "codes": {}},
        user_data={"is_admin": False},
    )

    block = await blocks.handle_block(context)
    labels = button_labels(block["reply_markup"])

    assert ("👤 User Menu" in labels) is shown
    assert not any("Suggest" in label for label in labels)
    assert "💬 Send Feedback" not in labels


@pytest.mark.asyncio
async def test_main_menu_hides_submenu_items(monkeypatch):
    monkeypatch.setattr(blocks, "get_troubleshooter_content", lambda: SAMPLE_CONTENT)
    context = SimpleNamespace(bot_data={"codes": {}, "parts": []}, user_data={})

    labels = button_labels((await blocks.handle_block(context))["reply_markup"])

    assert "Torque" in labels
    assert "Hub" not in labels


@pytest.mark.asyncio
async def test_main_menu_shows_part_count():
    context = SimpleNamespace(
        bot_data={"codes": {}, "parts": [{}, {}, {}]}, user_data={}
    )

    labels = button_labels((await blocks.handle_block(context))["reply_markup"])

    assert "🔩 Search 3 Spare Parts" in labels
