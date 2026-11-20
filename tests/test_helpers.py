import logging
from pathlib import Path
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
    monkeypatch.setattr(helpers, "is_test_mode", lambda: False)
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A5", "WTA05"),
        ("a5", "WTA05"),
        ("WTB3", "WTB03"),
        ("wt b 12", "WTB12"),
        ("C07", "WTC07"),
    ],
)
def test_find_turbine_normalises(monkeypatch, text, expected):
    info = {"serial": 1000001, "ip": "192.0.2.10"}
    monkeypatch.setattr(SETTINGS.content, "WTG_MAP", {expected: info})
    assert helpers.find_wtg(text) == (expected, info)


def test_find_turbine_unknown_wtg_returns_none_info(monkeypatch):
    monkeypatch.setattr(SETTINGS.content, "WTG_MAP", {})
    assert helpers.find_wtg("A5") == ("WTA05", None)


@pytest.mark.parametrize("text", ["", "hello", "A123", "5A", "LA", "AB5", "LA5"])
def test_find_turbine_invalid(text):
    assert helpers.find_wtg(text) == (None, None)


def node(id, title, parent=None, kind="page", body="", order=1):
    return {
        "id": id,
        "parent_id": parent,
        "type": kind,
        "title": title,
        "body": body,
        "sort_order": order,
        "edits": [],
    }


def test_get_troubleshooter_content_builds_entries(monkeypatch):
    monkeypatch.setattr(SETTINGS, "files_dir", "/media")
    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [
                node(1, "Power Board", body="power text"),
                node(2, "Fan-Unit Main", body="fan text", order=2),
                node(3, "Wiring", body="wiring text", order=3),
            ],
            "attachments": [
                {"node_id": 2, "type": "photo", "path": "images/fan.jpg"},
                {
                    "node_id": 3,
                    "type": "document",
                    "path": "pdf/wiring.pdf",
                    "file_id": "F3",
                },
            ],
        },
    )

    content = helpers.get_troubleshooter_content()

    assert content["troubleshooter:menu:1"] == {
        "type": "text",
        "title": "Power Board",
        "content": "power text",
        "file": None,
        "file_ids": [],
        "parent": None,
    }
    assert content["troubleshooter:menu:2"]["type"] == "photo"
    assert content["troubleshooter:menu:2"]["file"] == Path("/media") / "images/fan.jpg"
    assert content["troubleshooter:menu:3"]["type"] == "document"
    assert content["troubleshooter:menu:3"]["file_ids"] == ["F3"]
    assert content["troubleshooter:ioboard"] == {"type": "menu", "title": "IO Boards"}


def test_get_troubleshooter_content_builds_submenus(monkeypatch):
    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [
                node(1, "Torque", kind="submenu", body=None),
                node(3, "T1 Chart", parent=1, order=2),
                node(2, "Hub", parent=1, body="hub text"),
            ],
            "attachments": [],
        },
    )

    content = helpers.get_troubleshooter_content()

    assert content["troubleshooter:menu:1"] == {
        "type": "menu",
        "title": "Torque",
        "items": ["troubleshooter:menu:2", "troubleshooter:menu:3"],
        "parent": None,
    }
    assert content["troubleshooter:menu:2"]["parent"] == "troubleshooter:menu:1"
    assert content["troubleshooter:menu:2"]["content"] == "hub text"


def test_get_troubleshooter_content_sorted_by_title(monkeypatch):
    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [node(1, "zeta"), node(2, "Alpha", order=2), node(3, "mid")],
            "attachments": [],
        },
    )

    titles = [v["title"] for v in helpers.get_troubleshooter_content().values()]

    assert titles == sorted(titles, key=str.lower)


def test_no_menus_loaded_still_shows_io_boards(monkeypatch):
    monkeypatch.setattr(SETTINGS, "menu", None)

    assert list(helpers.get_troubleshooter_content()) == ["troubleshooter:ioboard"]


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,expected", [(123, True), ("123", True), (456, False)])
async def test_set_user_roles(user_id, expected):
    context = SimpleNamespace(
        user_data={}, bot_data={"troubleshooter_admins": {123: "admin"}}
    )

    await helpers.set_user_roles(context, user_id)

    assert context.user_data["is_admin"] is expected


@pytest.mark.asyncio
async def test_set_user_roles_no_admins_configured():
    context = SimpleNamespace(user_data={}, bot_data={})

    await helpers.set_user_roles(context, 123)

    assert context.user_data["is_admin"] is False


@pytest.mark.asyncio
async def test_set_user_roles_owner_is_admin(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", "999")
    context = SimpleNamespace(user_data={}, bot_data={})

    await helpers.set_user_roles(context, 999)

    assert context.user_data["is_admin"] is True
    assert context.user_data["is_approved"] is True


@pytest.mark.parametrize(
    "user_data,bot_data,expected",
    [
        ({"is_admin": True}, {"is_troubleshooter": True}, True),
        ({"is_admin": False}, {"is_troubleshooter": True}, False),
        ({}, {"is_troubleshooter": True}, False),
        ({}, {}, True),
    ],
)
def test_user_is_admin(user_data, bot_data, expected):
    context = SimpleNamespace(user_data=user_data, bot_data=bot_data)
    assert helpers.user_is_admin(context) is expected


def test_get_troubleshooter_content_nested_submenus(monkeypatch):
    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [
                node(1, "Service", kind="submenu", body=None),
                node(2, "Torque", parent=1, kind="submenu", body=None),
                node(3, "Hub", parent=2, body="hub text"),
            ],
            "attachments": [],
        },
    )

    content = helpers.get_troubleshooter_content()

    assert content["troubleshooter:menu:1"]["items"] == ["troubleshooter:menu:2"]
    assert content["troubleshooter:menu:2"]["parent"] == "troubleshooter:menu:1"
    assert content["troubleshooter:menu:3"]["parent"] == "troubleshooter:menu:2"


CODES = {
    "14031": {"id": 1, "code": "14031"},
    "14040": {"id": 2, "code": "14040"},
    "15031": {"id": 3, "code": "15031"},
    "9001": {"id": 4, "code": "9001"},
}


def test_find_codes_skips_exact_and_ranks_prefix_first():
    results = [c["code"] for c in helpers.find_codes("140", CODES)]

    assert results[:2] == ["14031", "14040"]
    assert "9001" not in results
    assert "14031" not in [c["code"] for c in helpers.find_codes("14031", CODES)]


def test_find_codes_empty_query():
    assert helpers.find_codes("  ", CODES) == []


PARTS = [
    {
        "part_no": "PN00081115",
        "description": "OILPUMP W MOTOR,280L/MIN",
        "section": "2.7 Gear Oil Pump and Cooler",
    },
    {
        "part_no": "PN10044840",
        "description": "Gear Oil Pump Bracket",
        "section": "2.7 Gear Oil Pump and Cooler",
    },
    {
        "part_no": "PN00400484",
        "description": "YAW MOTOR",
        "section": "7.1 YAW Drive",
    },
]


def test_find_parts_exact_part_number():
    assert helpers.find_parts("pn00400484", PARTS) == [PARTS[2]]


def test_find_parts_part_number_prefix():
    assert [p["part_no"] for p in helpers.find_parts("PN1", PARTS)] == ["PN10044840"]


def test_find_parts_accessories_ranked_lower():
    results = helpers.find_parts("gear oil pump", PARTS)

    assert results[0]["part_no"] == "PN00081115"
    assert results.index(PARTS[1]) > results.index(PARTS[0])


def test_find_parts_accessory_not_penalised_when_searched():
    assert helpers.find_parts("oil pump bracket", PARTS)[0]["part_no"] == "PN10044840"


def test_find_parts_empty_query():
    assert helpers.find_parts("", PARTS) == []
