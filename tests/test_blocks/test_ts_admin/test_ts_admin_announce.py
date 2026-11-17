import re
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
from turbine_troubleshooter.blocks.admin import broadcast
from turbine_troubleshooter.settings import SETTINGS
from turbine_troubleshooter.whats_new import WHATS_NEW

OWNER = 1


@pytest.fixture
def marks(monkeypatch):
    done = set()

    async def mark(name):
        if name in done:
            return False
        done.add(name)
        return True

    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", "-100")
    monkeypatch.setattr(broadcast, "setting_mark", mark)
    monkeypatch.setattr(broadcast, "version", lambda name: "9.9.0")
    monkeypatch.setattr(broadcast, "WHATS_NEW", {"9.9.0": "• Something new"})
    return done


def app(approved=frozenset({7})):
    return SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock()),
        bot_data={"troubleshooter_approved": set(approved)},
    )


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_owner_is_offered_the_note_once(marks):
    application = app()

    await broadcast.offer_update_note(application)
    await broadcast.offer_update_note(application)

    sent = application.bot.send_message.await_args_list
    assert len(sent) == 1
    assert sent[0].args[0] == "-100"
    assert "What's new in" in sent[0].args[1] and "9.9.0" in sent[0].args[1]
    assert "Something new" in sent[0].args[1]
    assert buttons(sent[0].kwargs["reply_markup"]) == [
        "troubleshooter:announce:send:9.9.0",
        "troubleshooter:announce:skip:9.9.0",
    ]
    assert marks == {"offered_9.9.0"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,marked",
    [
        ({"WHATS_NEW": {}}, False),
        ({"test_mode": True}, False),
        ({"announce_updates": "0"}, False),
        ({"approved": set()}, False),
    ],
    ids=["no-note", "test-mode", "turned-off", "nobody-to-tell"],
)
async def test_no_offer(monkeypatch, marks, change, marked):
    if "WHATS_NEW" in change:
        monkeypatch.setattr(broadcast, "WHATS_NEW", change["WHATS_NEW"])
    if "test_mode" in change:
        monkeypatch.setattr(SETTINGS, "test_mode", True)
    if "announce_updates" in change:
        monkeypatch.setattr(SETTINGS, "announce_updates", "0")
    application = app(change.get("approved", {7}))

    await broadcast.offer_update_note(application)

    application.bot.send_message.assert_not_awaited()
    assert (marks == {"offered_9.9.0"}) is marked


@pytest.mark.asyncio
async def test_no_offer_without_a_version(monkeypatch, marks):
    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(broadcast, "version", missing)
    application = app()

    await broadcast.offer_update_note(application)

    application.bot.send_message.assert_not_awaited()
    assert marks == set()


async def press(data, user_id):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="own", full_name="Own"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    await turbine_troubleshooter.handle_button(
        SimpleNamespace(callback_query=query),
        SimpleNamespace(bot_data={}, user_data={"is_admin": True}),
    )
    return query


@pytest.mark.asyncio
async def test_send_broadcasts_once(monkeypatch, marks):
    notify = AsyncMock(return_value=(12, 2, []))
    monkeypatch.setattr(broadcast, "send_notification_troubleshooter", notify)

    query = await press("troubleshooter:announce:send:9.9.0", OWNER)
    again = await press("troubleshooter:announce:send:9.9.0", OWNER)

    notify.assert_awaited_once()
    assert notify.await_args.args[1] == "broadcast"
    assert (
        notify.await_args.kwargs["message"]
        == f"What's new in {SETTINGS.name}:\n\n• Something new"
    )
    assert (
        query.edit_message_text.await_args.args[0]
        == "📢 Sent the 9.9.0 update to 12 users. 2 have blocked the bot."
    )
    again.answer.assert_awaited_once_with("It's already been sent.", show_alert=True)


@pytest.mark.asyncio
async def test_skip_sends_nothing(monkeypatch, marks):
    notify = AsyncMock()
    monkeypatch.setattr(broadcast, "send_notification_troubleshooter", notify)

    query = await press("troubleshooter:announce:skip:9.9.0", OWNER)

    notify.assert_not_awaited()
    assert (
        query.edit_message_text.await_args.args[0]
        == "❌ Skipped. The 9.9.0 note wasn't sent."
    )


@pytest.mark.asyncio
async def test_only_the_owner_can_send(monkeypatch, marks):
    notify = AsyncMock()
    monkeypatch.setattr(broadcast, "send_notification_troubleshooter", notify)

    query = await press("troubleshooter:announce:send:9.9.0", 5)

    notify.assert_not_awaited()
    query.answer.assert_awaited_once_with(
        "⚠️ Only the owner can do that.", show_alert=True
    )
    assert marks == set()


def test_notes_are_keyed_by_version_and_fit_in_a_message():
    for key, note in WHATS_NEW.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", key)
        assert 0 < len(note) < 3500
