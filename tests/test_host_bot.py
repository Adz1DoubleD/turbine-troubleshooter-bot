from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import turbine_troubleshooter
from turbine_troubleshooter.blocks.admin import users as admin_users


def bots(monkeypatch, is_troubleshooter):
    own = SimpleNamespace(send_message=AsyncMock())
    host = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(turbine_troubleshooter, "application", SimpleNamespace(bot=own))
    context = SimpleNamespace(
        bot=own if is_troubleshooter else host,
        bot_data={"is_troubleshooter": is_troubleshooter},
    )
    return context, own, host


@pytest.mark.asyncio
@pytest.mark.parametrize("is_troubleshooter", [True, False])
async def test_user_is_told_through_the_troubleshooter_bot(
    monkeypatch, is_troubleshooter
):
    context, own, host = bots(monkeypatch, is_troubleshooter)

    await admin_users.tell_user(context, 7, "✅ Access approved")

    assert own.send_message.await_args.args[:2] == (7, "✅ Access approved")
    host.send_message.assert_not_awaited()
