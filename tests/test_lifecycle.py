from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import troubleshooter
from troubleshooter.settings import SETTINGS


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
    monkeypatch.setattr(troubleshooter.Application, "builder", lambda: builder)
    monkeypatch.setattr(troubleshooter, "close_db", AsyncMock())
    monkeypatch.setattr(troubleshooter, "application", None)
    return app


@pytest.mark.asyncio
async def test_start_loads_its_own_data_and_shares_it(monkeypatch, fake_app):
    async def load(app):
        app.bot_data["codes"] = {"E1": {}}

    monkeypatch.setattr(troubleshooter, "init_troubleshooter_db", load)
    host = SimpleNamespace(bot_data={})

    app = await troubleshooter.start_troubleshooter_bot(share_with=host, name="Site")

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
    monkeypatch.setattr(troubleshooter, "init_troubleshooter_db", AsyncMock())

    app = await troubleshooter.start_troubleshooter_bot()

    assert app.bot_data["codes"] == {}
    assert app.bot_data["parts"] == []
    assert app.bot_data["troubleshooter_approved"] == set()


@pytest.mark.asyncio
async def test_stop_shuts_down_and_closes_db(monkeypatch, fake_app):
    monkeypatch.setattr(troubleshooter, "init_troubleshooter_db", AsyncMock())
    await troubleshooter.start_troubleshooter_bot()
    fake_app.updater.running = True
    fake_app.running = True
    fake_app._initialized = True

    await troubleshooter.stop_troubleshooter_bot()

    fake_app.updater.stop.assert_awaited_once()
    fake_app.stop.assert_awaited_once()
    fake_app.shutdown.assert_awaited_once()
    troubleshooter.close_db.assert_awaited_once()
    assert troubleshooter.application is None


@pytest.mark.asyncio
async def test_stop_before_start_only_closes_db(fake_app):
    await troubleshooter.stop_troubleshooter_bot()

    troubleshooter.close_db.assert_awaited_once()
