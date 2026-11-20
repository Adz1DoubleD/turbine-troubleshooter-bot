from types import SimpleNamespace

import pytest

from turbine_troubleshooter.blocks import parts

PART = {
    "id": 7,
    "part_no": "PN00400484",
    "description": "YAW MOTOR",
    "section": "7.1 YAW Drive",
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
async def test_parts_search_hides_empty_section():
    part = {"id": 3, "part_no": "PN999", "description": "Admin part", "section": ""}
    context, sent = parts_context(part_list=[part])

    await parts.handle_search(UPDATE, context, "admin part")

    assert "└ `PN999`" in sent[0]["text"]
    assert "├" not in sent[0]["text"]
