from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
import turbine_troubleshooter.db as db
from turbine_troubleshooter.blocks import admin as admin_menu
from turbine_troubleshooter.settings import SETTINGS

OWNER = 999
ADMIN = 5


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))


def make_query(data, user_id=OWNER):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), query


def buttons(query):
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_init_loads_notify_settings(make_cursor, patch_session):
    cur = make_cursor()

    async def fetchone():
        sql = cur.calls[-1][0]
        return {"t": sql.split("'")[1]} if sql.startswith("SHOW TABLES") else None

    async def fetchall():
        if cur.calls[-1][0] == "SELECT name, value FROM settings":
            return [{"name": "notify_edited", "value": 0}]
        return []

    cur.fetchone = AsyncMock(side_effect=fetchone)
    cur.fetchall = AsyncMock(side_effect=fetchall)
    patch_session(db, cur)

    await db.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert SETTINGS.notify_settings == {"notify_edited": 0}
    assert not any("CREATE TABLE settings" in c[0] for c in cur.calls)


@pytest.mark.asyncio
async def test_setting_toggle_flips_and_caches(make_cursor, patch_session):
    cur = make_cursor(fetchone=[{"value": 0}])
    patch_session(db, cur)

    assert await db.setting_toggle("notify_added") == 0

    assert "ON DUPLICATE KEY UPDATE value = 1 - value" in cur.calls[0][0]
    assert cur.calls[0][1] == ("notify_added",)
    assert SETTINGS.notify_settings["notify_added"] == 0


@pytest.mark.asyncio
async def test_notify_screen_shows_each_setting(monkeypatch):
    monkeypatch.setattr(SETTINGS, "notify_settings", {"notify_deleted": 0})
    toggle = AsyncMock()
    monkeypatch.setattr(admin_menu, "setting_toggle", toggle)
    update, query = make_query("troubleshooter:notify_users")

    await admin_menu.button_notify(update, SimpleNamespace())

    toggle.assert_not_awaited()
    assert buttons(query) == [
        ("✅ ➕ Added", "troubleshooter:notify_users:added"),
        ("✅ ✏️ Edited", "troubleshooter:notify_users:edited"),
        ("❌ 🗑️ Deleted", "troubleshooter:notify_users:deleted"),
        ("🔙 Back", "troubleshooter:admin_menu"),
    ]


@pytest.mark.asyncio
async def test_notify_button_toggles_setting(monkeypatch):
    async def toggle(name):
        SETTINGS.notify_settings[name] = 0

    monkeypatch.setattr(SETTINGS, "notify_settings", {})
    monkeypatch.setattr(admin_menu, "setting_toggle", toggle)
    update, query = make_query("troubleshooter:notify_users:added")

    await admin_menu.button_notify(update, SimpleNamespace())

    assert buttons(query)[0][0] == "❌ ➕ Added"


@pytest.mark.asyncio
async def test_notify_is_owner_only(monkeypatch):
    toggle = AsyncMock()
    monkeypatch.setattr(admin_menu, "setting_toggle", toggle)
    update, query = make_query("troubleshooter:notify_users:added", user_id=ADMIN)

    await admin_menu.button_notify(update, SimpleNamespace())

    toggle.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    assert query.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_notify_routes_for_admins(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(admin_menu, "button_notify", called)
    update, query = make_query("troubleshooter:notify_users:edited")
    context = SimpleNamespace(
        user_data={"is_admin": True, "is_approved": True},
        bot_data={"is_troubleshooter": True},
    )

    await turbine_troubleshooter.handle_button(update, context)

    called.assert_awaited_once()
