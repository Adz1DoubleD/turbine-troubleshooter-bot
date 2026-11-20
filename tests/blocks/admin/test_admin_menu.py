from types import SimpleNamespace

import pytest

import turbine_troubleshooter.blocks.admin as admin
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


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,owner_buttons", [(OWNER, True), (OTHER, False)])
async def test_admin_panel_owner_only_buttons(user_id, owner_buttons):
    update, calls = make_update("troubleshooter:admin_menu", user_id=user_id)
    context, _ = make_context()

    await admin.handle_block(update, context)

    shown = labels(calls["edits"][0]["reply_markup"])
    assert ("📢 Broadcast" in shown) is owner_buttons
    assert "➕ Add Code" in shown
    assert "🔩 Add Part" in shown
    assert "👥 Users" in shown
    assert "📤 Export" in shown
    assert not any("Manage" in label for label in shown)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id,label", [(OWNER, "📥 Requests (2)"), (OTHER, "👥 Users")]
)
async def test_admin_panel_shows_pending_count_to_owner(user_id, label):
    update, calls = make_update("troubleshooter:admin_menu", user_id=user_id)
    context, _ = make_context(
        bot_data={
            "pending_access_requests": {7: "@a"},
            "pending_admin_requests": {8: "@b"},
        }
    )

    await admin.handle_block(update, context)

    assert label in labels(calls["edits"][0]["reply_markup"])


@pytest.mark.asyncio
async def test_admin_panel_rejects_non_admin():
    update, calls = make_update("troubleshooter:admin_menu", user_id=OTHER)
    context, _ = make_context(is_admin=False)

    await admin.handle_block(update, context)

    assert calls["edits"] == []
    assert "Unauthorized" in calls["answers"][0]
