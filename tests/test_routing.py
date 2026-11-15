from types import SimpleNamespace

import pytest

import troubleshooter
from troubleshooter.blocks import admin, codes, io_boards, parts, user, wtg
from troubleshooter.blocks.admin import broadcast as admin_broadcast
from troubleshooter.blocks.admin import codes as admin_codes
from troubleshooter.blocks.admin import parts as admin_parts
from troubleshooter.blocks.admin import users as admin_users


@pytest.fixture(autouse=True)
def no_content(monkeypatch):
    monkeypatch.setattr(troubleshooter, "get_troubleshooter_content", lambda: {})


def make_update(data, user_id=123):
    edits = []

    async def edit_message_text(text, **kwargs):
        edits.append({"text": text, **kwargs})

    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        edit_message_text=edit_message_text,
    )
    return SimpleNamespace(callback_query=query), edits


def make_text_update(text):
    async def delete():
        pass

    return SimpleNamespace(
        message=SimpleNamespace(text=text, delete=delete),
        effective_chat=SimpleNamespace(id=1),
    )


def make_context(is_admin, user_data=None):
    return SimpleNamespace(
        user_data={"is_admin": is_admin, **(user_data or {})},
        bot_data={"is_troubleshooter": True},
    )


def record(monkeypatch, module, name):
    called = []

    async def fake(*args, **kwargs):
        called.append(args)

    monkeypatch.setattr(module, name, fake)
    return called


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


SAMPLE_CONTENT = {
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
async def test_submenu_lists_items_and_backs_to_main(monkeypatch):
    monkeypatch.setattr(
        troubleshooter, "get_troubleshooter_content", lambda: SAMPLE_CONTENT
    )
    update, edits = make_update("troubleshooter:torque")
    update.callback_query.message = SimpleNamespace(text="menu")

    await troubleshooter.handle_button(
        update, SimpleNamespace(bot_data={}, user_data={})
    )

    assert "*Torque*" in edits[0]["text"]
    assert callbacks(edits[0]["reply_markup"]) == [
        "troubleshooter:torque:hub",
        "back:troubleshooter",
    ]


@pytest.mark.asyncio
async def test_submenu_item_backs_to_parent(monkeypatch):
    monkeypatch.setattr(
        troubleshooter, "get_troubleshooter_content", lambda: SAMPLE_CONTENT
    )
    update, edits = make_update("troubleshooter:torque:hub")

    await troubleshooter.handle_button(
        update, SimpleNamespace(bot_data={}, user_data={})
    )

    assert "hub text" in edits[0]["text"]
    assert callbacks(edits[0]["reply_markup"]) == ["troubleshooter:torque"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,module,name",
    [
        ("troubleshooter:user_menu", user, "button_menu"),
        ("troubleshooter:notifications:toggle", user, "button_menu"),
        ("troubleshooter:notifications:alert", user, "button_alert_toggle"),
        ("troubleshooter:feedback", user, "button_feedback"),
        ("admin:request", user, "button_request_admin"),
        ("admin:approve:9", admin_users, "button_admin_approve"),
        ("admin:deny:9", admin_users, "button_admin_deny"),
        ("troubleshooter:access_request", user, "button_request_access"),
        ("access:approve:9", admin_users, "button_access_approve"),
        ("access:deny:9", admin_users, "button_access_deny"),
        ("troubleshooter:parts_search", parts, "button_search"),
        ("troubleshooter:wtg_search", wtg, "button_search"),
        ("troubleshooter:code_search", codes, "button_search"),
        ("troubleshooter:code_search:5", codes, "button_page"),
        ("troubleshooter:ioboard:io1", io_boards, "button_board"),
    ],
)
async def test_buttons_for_everyone(monkeypatch, data, module, name):
    called = record(monkeypatch, module, name)
    update, _ = make_update(data)

    await troubleshooter.handle_button(update, make_context(is_admin=False))

    assert len(called) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,module,name",
    [
        ("troubleshooter:admin_menu", admin, "handle_block"),
        ("troubleshooter:part_add", admin_parts, "button_part_add"),
        ("troubleshooter:part_edit:7", admin_parts, "button_part_edit"),
        (
            "troubleshooter:part_edit_field:description:7",
            admin_parts,
            "button_part_edit_field",
        ),
        (
            "troubleshooter:part_confirm_del:7",
            admin_parts,
            "button_part_delete_confirm",
        ),
        ("troubleshooter:part_delete:7", admin_parts, "button_part_delete"),
        ("troubleshooter:code_add", admin_codes, "button_code_add"),
        ("troubleshooter:code_edit:E1", admin_codes, "button_code_edit"),
        (
            "troubleshooter:code_edit_field:advice",
            admin_codes,
            "button_code_edit_field",
        ),
        ("troubleshooter:code_edit_save", admin_codes, "button_code_edit_save"),
        (
            "troubleshooter:code_confirm_del:E1",
            admin_codes,
            "button_code_delete_confirm",
        ),
        ("troubleshooter:code_delete:E1", admin_codes, "button_code_delete"),
        ("troubleshooter:user_list", admin_users, "button_users_list"),
        ("troubleshooter:user_list:login:2", admin_users, "button_users_list"),
        ("troubleshooter:user:7", admin_users, "button_user_card"),
        (
            "troubleshooter:user_act:admin_add:7",
            admin_users,
            "button_user_action",
        ),
        ("troubleshooter:user_do:admin_add:7", admin_users, "button_user_do"),
        ("troubleshooter:pending", admin_users, "button_pending"),
        ("troubleshooter:pending:2", admin_users, "button_pending"),
        ("troubleshooter:user_search", admin_users, "button_user_search"),
        ("troubleshooter:broadcast", admin_broadcast, "button_broadcast"),
        ("troubleshooter:export_menu", admin, "button_export_menu"),
        ("export:codes", admin, "button_export"),
    ],
)
@pytest.mark.parametrize("is_admin", [True, False])
async def test_admin_buttons_only_for_admins(monkeypatch, data, module, name, is_admin):
    called = record(monkeypatch, module, name)
    update, _ = make_update(data)

    await troubleshooter.handle_button(update, make_context(is_admin))

    assert len(called) == (1 if is_admin else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,module,name,admin_only",
    [
        ("troubleshooter:code_search", codes, "handle_search", False),
        ("troubleshooter:parts_search", parts, "handle_search", False),
        ("troubleshooter:wtg_search", wtg, "handle_search", False),
        ("troubleshooter:feedback", user, "handle_feedback", False),
        ("troubleshooter:broadcast", admin_broadcast, "handle_broadcast", False),
        ("troubleshooter:code_add:code", admin_codes, "handle_code_add", True),
        ("troubleshooter:part_add:part_no", admin_parts, "handle_part_add", True),
        ("troubleshooter:user_search", admin_users, "handle_user_search", True),
        (
            "troubleshooter:part_await_edit:description:7",
            admin_parts,
            "handle_part_edit",
            True,
        ),
    ],
)
@pytest.mark.parametrize("is_admin", [True, False])
async def test_text_routing(monkeypatch, state, module, name, admin_only, is_admin):
    called = record(monkeypatch, module, name)
    update = make_text_update(" New text ")

    await troubleshooter.handle_text_input(
        update, make_context(is_admin, {"state": state})
    )

    if is_admin or not admin_only:
        assert len(called) == 1
        assert called[0][2] == "New text"
    else:
        assert called == []


@pytest.mark.asyncio
async def test_code_edit_text_updates_buffer(monkeypatch):
    called = record(monkeypatch, admin_codes, "handle_code_edit")
    context = make_context(
        True,
        {
            "state": "troubleshooter:code_await_edit:advice",
            "code_edit_buffer": {"code": "E1", "advice": "old"},
            "last_msg_id": 55,
        },
    )

    await troubleshooter.handle_text_input(make_text_update("new advice"), context)

    assert context.user_data["code_edit_buffer"]["advice"] == "new advice"
    assert context.user_data["state"] is None
    assert called == [(context, 1, 55)]
