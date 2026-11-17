import logging
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import turbine_troubleshooter
from turbine_troubleshooter.settings import SETTINGS


@pytest.fixture
def fake_app(monkeypatch):
    app = MagicMock()
    app.bot_data = {}
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.updater.start_polling = AsyncMock()
    app.updater.stop = AsyncMock()
    builder = MagicMock()
    builder.token.return_value.build.return_value = app
    monkeypatch.setattr(turbine_troubleshooter.Application, "builder", lambda: builder)
    monkeypatch.setattr(turbine_troubleshooter, "close_db", AsyncMock())
    monkeypatch.setattr(turbine_troubleshooter, "application", None)
    monkeypatch.setattr(SETTINGS, "owner_id", "42")
    monkeypatch.setenv("TROUBLESHOOTER_DB_URL", "mysql://u:p@db-host:3306/ts")
    app.builder = builder
    return app


@pytest.mark.asyncio
async def test_start_refuses_without_required_settings(monkeypatch, fake_app):
    monkeypatch.setattr(SETTINGS, "token", None)
    monkeypatch.setattr(SETTINGS, "owner_id", None)
    monkeypatch.delenv("TROUBLESHOOTER_DB_URL")
    monkeypatch.delenv("JAWSDB_URL", raising=False)
    for var in ("TROUBLESHOOTER_BOT_TOKEN", "TROUBLESHOOTER_OWNER_ID"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError) as error:
        await turbine_troubleshooter.start_troubleshooter_bot()

    assert str(error.value) == (
        "Troubleshooter needs these settings: TROUBLESHOOTER_BOT_TOKEN, "
        "TROUBLESHOOTER_OWNER_ID, TROUBLESHOOTER_DB_URL"
    )
    fake_app.builder.token.assert_not_called()


@pytest.mark.asyncio
async def test_host_database_url_does_not_count(monkeypatch, fake_app):
    init = AsyncMock()
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", init)
    monkeypatch.delenv("TROUBLESHOOTER_DB_URL")
    monkeypatch.setenv("JAWSDB_URL", "mysql://u:p@main-host:3306/main")

    with pytest.raises(ValueError, match="TROUBLESHOOTER_DB_URL"):
        await turbine_troubleshooter.start_troubleshooter_bot()

    init.assert_not_awaited()
    fake_app.builder.token.assert_not_called()


@pytest.mark.asyncio
async def test_alerts_go_to_owner_when_unset(monkeypatch, fake_app):
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())
    monkeypatch.setattr(SETTINGS, "alerts_chat_id", None)
    monkeypatch.delenv("TROUBLESHOOTER_ALERTS_CHAT_ID", raising=False)

    await turbine_troubleshooter.start_troubleshooter_bot()

    assert SETTINGS.alerts_chat_id == "42"


@pytest.mark.asyncio
async def test_alerts_chat_kept_when_set(monkeypatch, fake_app):
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())

    await turbine_troubleshooter.start_troubleshooter_bot(alerts_chat_id="-100")

    assert SETTINGS.alerts_chat_id == "-100"


@pytest.mark.asyncio
async def test_standalone_prints_missing_settings_without_traceback(
    monkeypatch, capsys
):
    import turbine_troubleshooter.__main__ as standalone

    monkeypatch.setattr(standalone, "load_dotenv", lambda: None)
    monkeypatch.setattr(standalone.sentry_sdk, "init", lambda **kwargs: None)
    monkeypatch.setattr(
        standalone,
        "start_troubleshooter_bot",
        AsyncMock(side_effect=ValueError("Troubleshooter needs these settings: X")),
    )
    stop = AsyncMock()
    monkeypatch.setattr(standalone, "stop_troubleshooter_bot", stop)

    await standalone.main()

    out = capsys.readouterr().out
    assert "❌ Troubleshooter needs these settings: X. Add them to .env" in out
    stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_loads_its_own_data_and_shares_it(monkeypatch, fake_app):
    async def load(app):
        app.bot_data["codes"] = {"E1": {}}

    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", load)
    host = SimpleNamespace(bot_data={})

    app = await turbine_troubleshooter.start_troubleshooter_bot(
        share_with=host, name="Site"
    )

    assert app is fake_app
    assert app.bot_data["is_troubleshooter"] is True
    assert host.bot_data["codes"] is app.bot_data["codes"] == {"E1": {}}
    assert (
        host.bot_data["troubleshooter_approved"]
        is app.bot_data["troubleshooter_approved"]
    )
    assert "is_troubleshooter" not in host.bot_data
    assert SETTINGS.name == "Site"
    fake_app.updater.start_polling.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_without_host_fills_defaults_when_db_fails(monkeypatch, fake_app):
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())

    app = await turbine_troubleshooter.start_troubleshooter_bot()

    assert app.bot_data["codes"] == {}
    assert app.bot_data["parts"] == []
    assert app.bot_data["troubleshooter_approved"] == set()


@pytest.mark.asyncio
async def test_stop_shuts_down_and_closes_db(monkeypatch, fake_app):
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())
    await turbine_troubleshooter.start_troubleshooter_bot()
    fake_app.updater.running = True
    fake_app.running = True
    fake_app._initialized = True

    await turbine_troubleshooter.stop_troubleshooter_bot()

    fake_app.updater.stop.assert_awaited_once()
    fake_app.stop.assert_awaited_once()
    fake_app.shutdown.assert_awaited_once()
    turbine_troubleshooter.close_db.assert_awaited_once()
    assert turbine_troubleshooter.application is None


@pytest.mark.asyncio
async def test_stop_before_start_only_closes_db(fake_app):
    await turbine_troubleshooter.stop_troubleshooter_bot()

    turbine_troubleshooter.close_db.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["channel_post", "edited_channel_post"])
async def test_channel_posts_reach_no_message_handler(monkeypatch, fake_app, kind):
    from datetime import datetime

    from telegram import Chat, Message, Update
    from telegram.ext import MessageHandler

    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())
    await turbine_troubleshooter.start_troubleshooter_bot()
    post = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=-100, type=Chat.CHANNEL),
        text="📝 Content Suggestion",
    )
    update = Update(update_id=1, **{kind: post})

    handlers = [
        c.args[0]
        for c in fake_app.add_handler.call_args_list
        if isinstance(c.args[0], MessageHandler)
    ]
    assert len(handlers) == 1
    assert not any(h.check_update(update) for h in handlers)


def test_importing_changes_nothing_in_the_host():
    code = (
        "import logging, os; "
        "import turbine_troubleshooter; "
        "print(os.environ.get('PTB_TIMEDELTA'), "
        "len(logging.getLogger('telegram').filters), "
        "len(logging.getLogger('httpx').filters))"
    )
    env = {k: v for k, v in os.environ.items() if k != "PTB_TIMEDELTA"}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )

    assert out.stdout.split() == ["None", "0", "0"], out.stderr


@pytest.mark.asyncio
async def test_start_adds_noise_filters(monkeypatch, fake_app):
    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())
    for name in ("telegram", "httpx"):
        monkeypatch.setattr(logging.getLogger(name), "filters", [])

    await turbine_troubleshooter.start_troubleshooter_bot()

    for name in ("telegram", "httpx"):
        assert turbine_troubleshooter.error_handler_noise_filter in (
            logging.getLogger(name).filters
        )


@pytest.mark.asyncio
async def test_host_shares_every_piece_of_data_the_package_uses(monkeypatch, fake_app):
    import re
    from pathlib import Path

    monkeypatch.setattr(turbine_troubleshooter, "init_troubleshooter_db", AsyncMock())
    host = SimpleNamespace(bot_data={})
    source = "".join(
        p.read_text(encoding="utf-8")
        for p in Path(turbine_troubleshooter.__file__).parent.rglob("*.py")
    )
    used = set(re.findall(r'bot_data(?:\.\w+\()?\[?"(\w+)"', source))
    used |= {
        f"pending_{kind}_requests"
        for kind in ("access", "admin")
        if "pending_{kind}_requests" in source
    }

    await turbine_troubleshooter.start_troubleshooter_bot(share_with=host)

    assert used - {"is_troubleshooter"} <= set(host.bot_data)
    for key in host.bot_data:
        assert host.bot_data[key] is fake_app.bot_data[key]
