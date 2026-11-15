from types import SimpleNamespace

import pytest
from telegram.error import Forbidden, RetryAfter

import troubleshooter as tb
import troubleshooter.tools as notify
from troubleshooter.settings import SETTINGS


@pytest.fixture(autouse=True)
def not_local(monkeypatch):
    monkeypatch.setattr(notify, "is_local", lambda: False)


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def fake_send(chat_id, text, **kwargs):
        calls.append(chat_id)
        if chat_id == 2:
            raise Forbidden("blocked by user")
        if chat_id == 3:
            raise RuntimeError("network blip")

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=fake_send)),
    )

    async def _nosleep(*a, **k):
        pass

    monkeypatch.setattr(notify.asyncio, "sleep", _nosleep)
    return calls


@pytest.fixture
def users(monkeypatch):
    def _set(rows=None, error=None):
        async def fake_users_get():
            if error:
                raise error
            return [{"is_approved": 1, **r} for r in rows or []]

        monkeypatch.setattr(notify, "users_get", fake_users_get)

    return _set


@pytest.mark.asyncio
async def test_broadcast_counts_success_and_blocked(sent, users):
    users(
        [
            {"user_id": 1, "username": "alice"},
            {"user_id": 2, "username": "bob"},
            {"user_id": 4, "username": "carol"},
        ]
    )

    ok, blocked, names = await notify.send_notification_troubleshooter(
        action="broadcast", message="hello"
    )

    assert sent == [1, 2, 4]
    assert (ok, blocked) == (2, 1)
    assert names == ["@alice", "@carol"]


@pytest.mark.parametrize("action", ["broadcast", "code_added"])
@pytest.mark.asyncio
async def test_unapproved_users_get_no_notifications(sent, users, action):
    users(
        [
            {"user_id": 1, "username": "alice"},
            {"user_id": 2, "username": "stranger", "is_approved": 0},
            {"user_id": 3, "username": "admin", "is_approved": 0, "is_admin": 1},
        ]
    )

    await notify.send_notification_troubleshooter(
        action=action, message="hello", code="E1", advice="secret advice"
    )

    assert 2 not in sent
    assert {1, 3} <= set(sent)


@pytest.mark.asyncio
async def test_broadcast_does_not_hit_alerts(sent, users):
    users([{"user_id": 1, "username": "alice"}])

    await notify.send_notification_troubleshooter(action="broadcast", message="hi")

    assert SETTINGS.alerts_chat_id not in sent


@pytest.mark.asyncio
async def test_broadcast_db_error_returns_zeros(sent, users):
    users(error=RuntimeError("db down"))

    assert await notify.send_notification_troubleshooter(
        action="broadcast", message="hi"
    ) == (0, 0, [])
    assert sent == []


@pytest.mark.asyncio
async def test_new_user_only_sends_to_alerts(sent, users):
    users([{"user_id": 1, "username": "alice"}])
    newbie = SimpleNamespace(id=99, username="newbie", full_name="New Bie")

    result = await notify.send_notification_troubleshooter(newbie)

    assert sent == [SETTINGS.alerts_chat_id]
    assert result == (0, 0, [])


@pytest.mark.asyncio
async def test_code_change_skips_editor_and_hits_alerts(sent, users):
    users(
        [
            {"user_id": 1, "username": "alice"},
            {"user_id": 5, "username": "editor"},
        ]
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    ok, blocked, names = await notify.send_notification_troubleshooter(
        editor, "code_added", "E101", "Check fuse", "Fuse 5A"
    )

    assert sent == [SETTINGS.alerts_chat_id, 1]
    assert (ok, blocked, names) == (1, 0, ["@alice"])


@pytest.mark.asyncio
async def test_deleted_code_broadcasts_without_advice(sent, users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])

    texts = []

    async def capture_send(chat_id, text, **kwargs):
        texts.append(text)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )

    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")
    ok, _, _ = await notify.send_notification_troubleshooter(
        editor, "code_deleted", "E101"
    )

    assert ok == 1
    assert "Code Deleted" in texts[0]
    assert "E101" in texts[0]
    assert "Advice" not in texts[0]
    assert "Parts" not in texts[0]


@pytest.mark.asyncio
async def test_other_errors_not_counted_as_blocked(sent, users):
    users([{"user_id": 3, "username": "dave"}])

    assert await notify.send_notification_troubleshooter(
        action="broadcast", message="hi"
    ) == (0, 0, [])


@pytest.mark.asyncio
async def test_retry_after_retries_once_then_succeeds(users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])

    attempts = []
    sleeps = []

    async def flaky_send(chat_id, text, **kwargs):
        attempts.append(chat_id)
        if len(attempts) == 1:
            raise RetryAfter(5)

    async def record_sleep(seconds, *a, **k):
        sleeps.append(seconds)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=flaky_send)),
    )
    monkeypatch.setattr(notify.asyncio, "sleep", record_sleep)

    ok, blocked, names = await notify.send_notification_troubleshooter(
        action="broadcast", message="hi"
    )

    assert attempts == [1, 1]
    assert 5 in sleeps
    assert (ok, blocked, names) == (1, 0, ["@alice"])


@pytest.mark.asyncio
async def test_retry_after_twice_gives_up_without_counting_blocked(users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])

    async def always_limited(chat_id, text, **kwargs):
        raise RetryAfter(1)

    async def _nosleep(*a, **k):
        pass

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=always_limited)),
    )
    monkeypatch.setattr(notify.asyncio, "sleep", _nosleep)

    assert await notify.send_notification_troubleshooter(
        action="broadcast", message="hi"
    ) == (0, 0, [])


@pytest.mark.asyncio
async def test_code_text_is_markdown_escaped(users, monkeypatch):
    users([])

    texts = []

    async def capture_send(chat_id, text, **kwargs):
        texts.append(text)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )

    editor = SimpleNamespace(id=5, username="ed_itor", full_name="Ed Itor")
    await notify.send_notification_troubleshooter(
        editor, "code_added", "E_1", "Check *fuse*", "PN_123"
    )

    assert "E\\_1" in texts[0]
    assert "Check \\*fuse\\*" in texts[0]
    assert "PN\\_123" in texts[0]
    assert "@ed\\_itor" in texts[0]


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
    assert notify.find_wtg(text) == (expected, info)


def test_find_turbine_unknown_wtg_returns_none_info(monkeypatch):
    monkeypatch.setattr(SETTINGS.content, "WTG_MAP", {})
    assert notify.find_wtg("A5") == ("WTA05", None)


@pytest.mark.parametrize("text", ["", "hello", "A123", "5A", "LA", "AB5", "LA5"])
def test_find_turbine_invalid(text):
    assert notify.find_wtg(text) == (None, None)


def test_get_troubleshooter_content_builds_entries(monkeypatch):
    monkeypatch.setattr(
        SETTINGS.content,
        "MODULES_MAP",
        {
            "Power Board": "power text",
            "Fan-Unit Main": {"text": "fan text", "photo": "fan.jpg"},
            "Wiring": {"text": "wiring text", "document": "wiring.pdf"},
            "Display": {"text": "display text"},
        },
    )

    content = notify.get_troubleshooter_content()

    assert content["troubleshooter:power_board"] == {
        "type": "text",
        "title": "Power Board",
        "content": "power text",
        "file": None,
        "parent": None,
    }
    assert content["troubleshooter:fan_unit_main"]["type"] == "photo"
    assert content["troubleshooter:fan_unit_main"]["file"] == "fan.jpg"
    assert content["troubleshooter:wiring"]["type"] == "document"
    assert content["troubleshooter:wiring"]["file"] == "wiring.pdf"
    assert content["troubleshooter:display"]["type"] == "text"
    assert content["troubleshooter:ioboard"] == {"type": "menu", "title": "IO Boards"}


def test_get_troubleshooter_content_builds_submenus(monkeypatch):
    monkeypatch.setattr(
        SETTINGS.content,
        "MODULES_MAP",
        {
            "Torque": {
                "menu": {
                    "Hub": "hub text",
                    "T1 Chart": {"text": " ", "document": "t1.pdf"},
                }
            },
        },
    )

    content = notify.get_troubleshooter_content()

    assert content["troubleshooter:torque"] == {
        "type": "menu",
        "title": "Torque",
        "items": ["troubleshooter:torque:hub", "troubleshooter:torque:t1_chart"],
        "parent": None,
    }
    assert content["troubleshooter:torque:hub"] == {
        "type": "text",
        "title": "Hub",
        "content": "hub text",
        "file": None,
        "parent": "troubleshooter:torque",
    }
    assert content["troubleshooter:torque:t1_chart"]["type"] == "document"
    assert content["troubleshooter:torque:t1_chart"]["file"] == "t1.pdf"
    assert (
        content["troubleshooter:torque:t1_chart"]["parent"] == "troubleshooter:torque"
    )


def test_get_troubleshooter_content_sorted_by_title(monkeypatch):
    monkeypatch.setattr(
        SETTINGS.content,
        "MODULES_MAP",
        {"zeta": "z", "Alpha": "a", "mid": "m"},
    )

    titles = [v["title"] for v in notify.get_troubleshooter_content().values()]

    assert titles == sorted(titles, key=str.lower)


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,expected", [(123, True), ("123", True), (456, False)])
async def test_set_user_roles(user_id, expected):
    context = SimpleNamespace(
        user_data={}, bot_data={"troubleshooter_admins": {123: "admin"}}
    )

    await notify.set_user_roles(context, user_id)

    assert context.user_data["is_admin"] is expected


@pytest.mark.asyncio
async def test_set_user_roles_no_admins_configured():
    context = SimpleNamespace(user_data={}, bot_data={})

    await notify.set_user_roles(context, 123)

    assert context.user_data["is_admin"] is False


@pytest.mark.asyncio
async def test_set_user_roles_owner_is_admin(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", "999")
    context = SimpleNamespace(user_data={}, bot_data={})

    await notify.set_user_roles(context, 999)

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
    assert notify.user_is_admin(context) is expected


@pytest.mark.asyncio
async def test_admin_revoked_only_messages_target(sent, users):
    users([{"user_id": 1, "username": "alice"}])

    result = await notify.send_notification_troubleshooter(
        action="admin_revoked", target_id=7
    )

    assert sent == [7]
    assert result == (0, 0, [])


@pytest.mark.asyncio
async def test_admin_revoked_target_blocked_does_not_raise(sent, users):
    users([])

    result = await notify.send_notification_troubleshooter(
        action="admin_revoked", target_id=2
    )

    assert sent == [2]
    assert result == (0, 0, [])


@pytest.mark.asyncio
async def test_broadcast_admins_only(sent, users):
    users(
        [
            {"user_id": 1, "username": "alice", "is_admin": 1},
            {"user_id": 4, "username": "bob", "is_admin": 0},
        ]
    )

    ok, _, names = await notify.send_notification_troubleshooter(
        action="broadcast", message="hi", audience="admins"
    )

    assert sent == [1]
    assert (ok, names) == (1, ["@alice"])


@pytest.mark.asyncio
async def test_broadcast_single_user(sent, users):
    users(
        [
            {"user_id": 1, "username": "alice", "is_admin": 0},
            {"user_id": 4, "username": "bob", "is_admin": 0},
        ]
    )

    ok, _, names = await notify.send_notification_troubleshooter(
        action="broadcast", message="hi", audience=4
    )

    assert sent == [4]
    assert (ok, names) == (1, ["@bob"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "audience,header",
    [
        ("all", "Acme Troubleshooter Update"),
        ("admins", "Acme Troubleshooter Admin Update"),
    ],
)
async def test_broadcast_header(users, monkeypatch, audience, header):
    users([{"user_id": 1, "username": "alice", "is_admin": 1}])

    texts = []

    async def capture_send(chat_id, text, **kwargs):
        texts.append(text)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )

    await notify.send_notification_troubleshooter(
        action="broadcast", message="hello_world", audience=audience
    )

    assert header in texts[0]
    assert "hello\\_world" in texts[0]


@pytest.mark.asyncio
async def test_bot_not_running_returns_zeros(users, monkeypatch):
    users([{"user_id": 1, "username": "alice", "is_admin": 0}])
    monkeypatch.setattr(tb, "application", None)

    assert await notify.send_notification_troubleshooter(
        action="broadcast", message="hi"
    ) == (0, 0, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["code_added", "code_edited", "code_deleted"])
@pytest.mark.parametrize("enabled,expected_users", [(1, [1, 4]), (0, [1])])
async def test_code_change_notify_setting(
    sent, users, monkeypatch, action, enabled, expected_users
):
    users(
        [
            {"user_id": 1, "username": "alice", "is_admin": 1},
            {"user_id": 4, "username": "bob", "is_admin": 0},
            {"user_id": 5, "username": "editor", "is_admin": 1},
        ]
    )
    monkeypatch.setitem(
        SETTINGS.notify_settings,
        f"notify_{action.split('_')[1]}",
        enabled,
    )

    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")
    await notify.send_notification_troubleshooter(editor, action, "E101")

    assert sent[0] == SETTINGS.alerts_chat_id
    assert sent[1:] == expected_users


@pytest.mark.asyncio
async def test_opted_out_users_skip_code_changes_but_get_broadcasts(sent, users):
    users(
        [
            {"user_id": 1, "username": "alice", "notifications_enabled": 1},
            {"user_id": 4, "username": "bob", "notifications_enabled": 0},
        ]
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(editor, "code_added", "E101")
    assert sent[1:] == [1]

    sent.clear()
    await notify.send_notification_troubleshooter(action="broadcast", message="hi")
    assert sent == [1, 4]


@pytest.mark.asyncio
async def test_opted_out_admin_still_skipped_when_admins_only(sent, users, monkeypatch):
    users(
        [
            {
                "user_id": 1,
                "username": "alice",
                "is_admin": 1,
                "notifications_enabled": 0,
            },
            {
                "user_id": 4,
                "username": "bob",
                "is_admin": 1,
                "notifications_enabled": 1,
            },
        ]
    )
    monkeypatch.setitem(SETTINGS.notify_settings, "notify_added", 0)

    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")
    await notify.send_notification_troubleshooter(editor, "code_added", "E101")

    assert sent[1:] == [4]


def test_get_troubleshooter_content_nested_submenus(monkeypatch):
    monkeypatch.setattr(
        SETTINGS.content,
        "MODULES_MAP",
        {"Service": {"menu": {"Torque": {"menu": {"Hub": "hub text"}}}}},
    )

    content = notify.get_troubleshooter_content()

    assert content["troubleshooter:service"]["items"] == [
        "troubleshooter:service:torque"
    ]
    assert (
        content["troubleshooter:service:torque"]["parent"] == "troubleshooter:service"
    )
    assert (
        content["troubleshooter:service:torque:hub"]["parent"]
        == "troubleshooter:service:torque"
    )


CODES = {
    "14031": {"id": 1, "code": "14031"},
    "14040": {"id": 2, "code": "14040"},
    "15031": {"id": 3, "code": "15031"},
    "9001": {"id": 4, "code": "9001"},
}


def test_find_codes_skips_exact_and_ranks_prefix_first():
    results = [c["code"] for c in notify.find_codes("140", CODES)]

    assert results[:2] == ["14031", "14040"]
    assert "9001" not in results
    assert "14031" not in [c["code"] for c in notify.find_codes("14031", CODES)]


def test_find_codes_empty_query():
    assert notify.find_codes("  ", CODES) == []


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
    assert notify.find_parts("pn00400484", PARTS) == [PARTS[2]]


def test_find_parts_part_number_prefix():
    assert [p["part_no"] for p in notify.find_parts("PN1", PARTS)] == ["PN10044840"]


def test_find_parts_accessories_ranked_lower():
    results = notify.find_parts("gear oil pump", PARTS)

    assert results[0]["part_no"] == "PN00081115"
    assert results.index(PARTS[1]) > results.index(PARTS[0])


def test_find_parts_accessory_not_penalised_when_searched():
    assert notify.find_parts("oil pump bracket", PARTS)[0]["part_no"] == "PN10044840"


def test_find_parts_empty_query():
    assert notify.find_parts("", PARTS) == []


@pytest.mark.asyncio
async def test_broadcast_has_close_button(users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])

    markups = []

    async def capture_send(chat_id, text, **kwargs):
        markups.append(kwargs.get("reply_markup"))

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )

    await notify.send_notification_troubleshooter(action="broadcast", message="hi")

    button = markups[0].inline_keyboard[0][0]
    assert button.callback_data == "cancel"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["part_added", "part_edited", "part_deleted"])
async def test_part_change_alerts_and_users(sent, users, action):
    users(
        [
            {"user_id": 1, "username": "alice", "notifications_enabled": 1},
            {"user_id": 4, "username": "bob", "notifications_enabled": 0},
            {"user_id": 5, "username": "editor"},
        ]
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    ok, _, names = await notify.send_notification_troubleshooter(
        editor, action, "PN123", "New pump"
    )

    assert sent == [SETTINGS.alerts_chat_id, 1]
    assert (ok, names) == (1, ["@alice"])


@pytest.mark.asyncio
async def test_part_change_setting_off_admins_only(sent, users, monkeypatch):
    users(
        [
            {"user_id": 1, "username": "alice", "is_admin": 1},
            {"user_id": 4, "username": "bob", "is_admin": 0},
        ]
    )
    monkeypatch.setitem(SETTINGS.notify_settings, "notify_added", 0)
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(
        editor, "part_added", "PN123", "New pump"
    )

    assert sent == [SETTINGS.alerts_chat_id, 1]


@pytest.mark.asyncio
async def test_unknown_action_raises(sent, users):
    with pytest.raises(ValueError):
        await notify.send_notification_troubleshooter(action="nope")


@pytest.mark.asyncio
async def test_code_alert_users_get_toggle_but_alerts_chat_does_not(users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])
    markups = {}

    async def capture_send(chat_id, text, **kwargs):
        markups[chat_id] = kwargs["reply_markup"]

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(editor, "part_added", "PN1", "Pump")

    def cbs(markup):
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    assert cbs(markups[SETTINGS.alerts_chat_id]) == ["cancel"]
    assert cbs(markups[1]) == ["troubleshooter:notifications:alert", "cancel"]


@pytest.mark.asyncio
async def test_broadcast_has_no_toggle(users, monkeypatch):
    users([{"user_id": 1, "username": "alice"}])
    markups = []

    async def capture_send(chat_id, text, **kwargs):
        markups.append(kwargs["reply_markup"])

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )

    await notify.send_notification_troubleshooter(action="broadcast", message="hi")

    assert [b.callback_data for row in markups[0].inline_keyboard for b in row] == [
        "cancel"
    ]


@pytest.mark.parametrize(
    "enabled,label",
    [(True, "🔕 Turn Off Notifications"), (False, "🔔 Turn On Notifications")],
)
def test_alert_markup_label(enabled, label):
    assert notify.alert_markup(enabled).inline_keyboard[0][0].text == label


@pytest.mark.asyncio
async def test_part_edited_shows_the_change(users, monkeypatch):
    users([])
    texts = []

    async def capture_send(chat_id, text, **kwargs):
        texts.append(text)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(
        editor,
        "part_edited",
        "PN123",
        "New pump",
        message="Section: Random_Parts → Pumps",
    )

    assert "🔩 *Spare Part Edited*" in texts[0]
    assert "• Part: `PN123`" in texts[0]
    assert "• Description: New pump" in texts[0]
    assert "• Change: Section: Random\\_Parts → Pumps" in texts[0]


@pytest.mark.asyncio
async def test_part_added_has_no_change_line(users, monkeypatch):
    users([])
    texts = []

    async def capture_send(chat_id, text, **kwargs):
        texts.append(text)

    monkeypatch.setattr(
        tb,
        "application",
        SimpleNamespace(bot=SimpleNamespace(send_message=capture_send)),
    )
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(
        editor, "part_added", "PN123", "New pump"
    )

    assert "Change:" not in texts[0]


@pytest.mark.asyncio
async def test_part_edited_follows_edited_setting(sent, users, monkeypatch):
    users(
        [
            {"user_id": 1, "username": "alice", "is_admin": 1},
            {"user_id": 4, "username": "bob", "is_admin": 0},
        ]
    )
    monkeypatch.setitem(SETTINGS.notify_settings, "notify_edited", 0)
    editor = SimpleNamespace(id=5, username="editor", full_name="Ed Itor")

    await notify.send_notification_troubleshooter(
        editor, "part_edited", "PN123", "New pump", message="Description: a → b"
    )

    assert sent == [SETTINGS.alerts_chat_id, 1]
