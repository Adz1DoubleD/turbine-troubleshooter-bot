from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks import parts

PART = {
    "id": 7,
    "part_no": "PN00400484",
    "description": "YAW MOTOR",
    "location": "B016",
}


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def parts_context(is_admin=False, part_list=None, state=None):
    sent = []

    async def edit(**kwargs):
        sent.append(kwargs)

    context = SimpleNamespace(
        bot=SimpleNamespace(edit_message_text=edit),
        user_data={"last_msg_id": 9, "is_admin": is_admin, "state": state},
        bot_data={
            "parts": part_list if part_list is not None else [dict(PART)],
            "is_troubleshooter": True,
        },
    )
    return context, sent


UPDATE = SimpleNamespace(effective_chat=SimpleNamespace(id=1))


@pytest.mark.asyncio
async def test_parts_search_lists_results():
    context, sent = parts_context(state="troubleshooter:parts_search")

    await parts.handle_search(UPDATE, context, "yaw motor")

    assert context.user_data["state"] is None
    assert "`PN00400484`" in sent[0]["text"]
    assert "YAW MOTOR" in sent[0]["text"]


@pytest.mark.asyncio
async def test_parts_search_no_results():
    context, sent = parts_context(part_list=[])

    await parts.handle_search(UPDATE, context, "unobtainium")

    assert "No Parts Found" in sent[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin,shown", [(True, True), (False, False)])
async def test_parts_search_admin_buttons(is_admin, shown):
    context, sent = parts_context(is_admin)

    await parts.handle_search(UPDATE, context, "yaw motor")

    cbs = callbacks(sent[0]["reply_markup"])
    assert ("troubleshooter:part_edit:7" in cbs) is shown
    assert ("troubleshooter:part_add" in cbs) is shown
    assert not any(cb.startswith("troubleshooter:part_confirm_del") for cb in cbs)


@pytest.mark.asyncio
async def test_parts_search_hides_an_empty_location():
    part = {"id": 3, "part_no": "PN999", "description": "Admin part"}
    context, sent = parts_context(part_list=[part])

    await parts.handle_search(UPDATE, context, "admin part")

    assert "└ Part No: `PN999`" in sent[0]["text"]
    assert "├" not in sent[0]["text"]


@pytest.mark.asyncio
async def test_parts_search_shows_both_numbers_and_the_location(monkeypatch):
    monkeypatch.setattr(parts.SETTINGS, "part_no_label", "Maker No")
    monkeypatch.setattr(parts.SETTINGS, "stock_no_label", "Store No")
    monkeypatch.setattr(parts.SETTINGS, "location_label", "Shelf")
    context, sent = parts_context(part_list=[{**PART, "stock_no": "10255168"}])

    await parts.handle_search(UPDATE, context, "yaw motor")

    assert (
        "*YAW MOTOR*\n├ Maker No: `PN00400484`\n├ Store No: `10255168`\n└ Shelf: B016"
    ) in sent[0]["text"]


@pytest.mark.asyncio
async def test_parts_can_be_found_by_their_location():
    other = {"id": 8, "part_no": "PN1", "description": "Wing nut"}
    context, sent = parts_context(part_list=[other, dict(PART)])

    await parts.handle_search(UPDATE, context, "b016")

    assert "YAW MOTOR" in sent[0]["text"]
    assert "Wing nut" not in sent[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["10255168", "102551"], ids=["whole", "start"])
async def test_parts_can_be_found_by_stock_number(text):
    other = {"id": 8, "part_no": "PN1", "description": "Wing nut"}
    context, sent = parts_context(part_list=[other, {**PART, "stock_no": "10255168"}])

    await parts.handle_search(UPDATE, context, text)

    assert "YAW MOTOR" in sent[0]["text"]
    assert "Wing nut" not in sent[0]["text"]


@pytest.mark.asyncio
async def test_a_part_without_a_stock_number_has_no_stock_line():
    context, sent = parts_context()

    await parts.handle_search(UPDATE, context, "yaw motor")

    assert "Stock No" not in sent[0]["text"]
