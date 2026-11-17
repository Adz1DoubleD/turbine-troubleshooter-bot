from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks import io_boards


def make_update(data):
    edits = []

    async def edit_message_text(text, **kwargs):
        edits.append({"text": text, **kwargs})

    query = SimpleNamespace(data=data, edit_message_text=edit_message_text)
    return SimpleNamespace(callback_query=query), edits


def button_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_io_board_menu_uses_names():
    labels = button_labels(io_boards.board_menu())

    assert "IO Board 1" in labels
    assert "IO Board 2" in labels


@pytest.mark.asyncio
async def test_io_board_shows_can_line():
    update, edits = make_update("troubleshooter:ioboard:io1")
    context = SimpleNamespace(
        bot_data={
            "io_boards": {"io1": [{"section": "X1", "pin": "1", "description": "24V"}]}
        },
        user_data={},
    )

    await io_boards.button_board(update, context)

    assert "*IO Board 1*" in edits[0]["text"]
    assert "_Node 1_" in edits[0]["text"]


@pytest.mark.asyncio
async def test_io_board_not_found_has_back_button():
    update, edits = make_update("troubleshooter:ioboard:io9")
    context = SimpleNamespace(bot_data={"io_boards": {}}, user_data={})

    await io_boards.button_board(update, context)

    assert "not found" in edits[0]["text"]
    assert callbacks(edits[0]["reply_markup"]) == ["troubleshooter:ioboard"]


@pytest.mark.asyncio
async def test_pins_without_a_description_show_just_the_pin():
    update, edits = make_update("troubleshooter:ioboard:io1")
    context = SimpleNamespace(
        bot_data={
            "io_boards": {
                "io1": [
                    {"section": "Inputs", "pin": "X1:1", "description": "Signal A"},
                    {"section": "Inputs", "pin": "X1:2", "description": None},
                    {"section": "Inputs", "pin": "X1:3", "description": "nan"},
                ]
            }
        },
        user_data={},
    )

    await io_boards.button_board(update, context)

    text = edits[0]["text"]
    assert "`X1:1` | Signal A\n" in text
    assert "`X1:2`\n" in text and "`X1:3`\n" in text
    assert "None" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sections,headings",
    [
        ((None, None), []),
        (("Inputs", None), ["🔹 *General*", "🔹 *Inputs*"]),
    ],
    ids=["no-sections", "some-sections"],
)
async def test_section_headings(sections, headings):
    update, edits = make_update("troubleshooter:ioboard:io1")
    pins = [
        {"section": s, "pin": f"X{i}", "description": None}
        for i, s in enumerate(sections, 1)
    ]
    context = SimpleNamespace(bot_data={"io_boards": {"io1": pins}}, user_data={})

    await io_boards.button_board(update, context)

    text = edits[0]["text"]
    assert [line for line in text.splitlines() if line.startswith("🔹")] == headings
    assert "`X1`" in text and "`X2`" in text
