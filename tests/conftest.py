import os
import sys
from unittest.mock import AsyncMock

import pytest

from turbine_troubleshooter import example_content
from turbine_troubleshooter.settings import SETTINGS

os.environ.setdefault("PTB_TIMEDELTA", "1")

NOISE_FILTERS = [
    "httpx.ReadError",
    "RemoteProtocolError",
    "Timed out",
    "Query is too old",
    "query id is invalid",
    "Message is not modified",
]


class FakeCursor:
    def __init__(
        self, *, fetchone=None, fetchall=None, rowcount=1, lastrowid=7, error=None
    ):
        self.fetchone_values = list(fetchone or [])
        self.fetchall_values = list(fetchall or [])
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.error = error
        self.calls = []
        self._fetchone_index = 0
        self._fetchall_index = 0
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchone = AsyncMock(side_effect=self._fetchone)
        self.fetchall = AsyncMock(side_effect=self._fetchall)

    async def _execute(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error

    async def _fetchone(self):
        if self._fetchone_index >= len(self.fetchone_values):
            return None
        value = self.fetchone_values[self._fetchone_index]
        self._fetchone_index += 1
        if isinstance(value, Exception):
            raise value
        return value

    async def _fetchall(self):
        if self._fetchall_index >= len(self.fetchall_values):
            return []
        value = self.fetchall_values[self._fetchall_index]
        self._fetchall_index += 1
        if isinstance(value, Exception):
            raise value
        return value


class FakeSession:
    def __init__(self, cursor):
        self.cursor = cursor

    async def __aenter__(self):
        return self.cursor

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __call__(self):
        return self


@pytest.fixture
def make_cursor():
    return FakeCursor


@pytest.fixture
def patch_session(monkeypatch):
    def _patch(module, cursor):
        session = FakeSession(cursor)
        targets = [module]
        if module.__name__.startswith("turbine_troubleshooter.db"):
            targets = [
                m
                for name, m in sys.modules.items()
                if name.startswith("turbine_troubleshooter.db")
                and hasattr(m, "db_session")
            ]
        for target in targets:
            monkeypatch.setattr(target, "db_session", session)
        return cursor

    return _patch


@pytest.fixture(autouse=True)
def troubleshooter_settings(monkeypatch):
    for name, value in {
        "name": "Acme Troubleshooter",
        "wtg_prefix": "WT",
        "token": "test-token",
        "owner_id": None,
        "alerts_chat_id": None,
        "timezone": "Europe/London",
        "noise_filters": NOISE_FILTERS,
        "notify_settings": {},
        "content": example_content,
        "menu": None,
        "files_dir": None,
        "cefas_buoy": None,
        "windquest_api_key": None,
        "windquest_api_token": None,
        "windquest_location": None,
        "test_mode": False,
        "announce_updates": True,
    }.items():
        monkeypatch.setattr(SETTINGS, name, value)
    return SETTINGS
