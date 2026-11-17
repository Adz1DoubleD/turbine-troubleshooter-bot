import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import turbine_troubleshooter
from turbine_troubleshooter.blocks.admin import files
from turbine_troubleshooter.settings import SETTINGS

OWNER = 1
ADMIN = 5
TOKEN = "github_pat_test_only"


def attachments():
    return [
        {
            "id": 8,
            "node_id": 3,
            "type": "document",
            "path": "pdf/safety.pdf",
            "file_id": "F8",
            "file_unique_id": "U8",
            "status": "pending",
        },
        {
            "id": 9,
            "node_id": 3,
            "type": "photo",
            "path": "images/safety.jpg",
            "file_id": "F9",
            "file_unique_id": "U9",
            "status": "committed",
        },
    ]


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(SETTINGS, "owner_id", str(OWNER))
    monkeypatch.setattr(SETTINGS, "files_repo", "owner/host-bot")
    monkeypatch.setattr(SETTINGS, "files_dir", "media")
    monkeypatch.setattr(SETTINGS, "files_repo_dir", "app/media/")
    monkeypatch.setattr(SETTINGS, "files_repo_token", TOKEN)
    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [
                {
                    "id": 3,
                    "parent_id": None,
                    "type": "page",
                    "title": "Safety",
                    "body": "x",
                    "sort_order": 1,
                    "edits": [],
                }
            ],
            "attachments": attachments(),
        },
    )


@pytest.fixture
def github(monkeypatch):
    calls = SimpleNamespace(puts=[], status=201, error=None, saved=[])

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, headers, json):
            calls.puts.append((url, headers, json))
            if calls.error:
                raise calls.error
            return SimpleNamespace(status_code=calls.status)

    async def status(attachment_id, value):
        calls.saved.append((attachment_id, value))

    monkeypatch.setattr(files.httpx, "AsyncClient", Client)
    monkeypatch.setattr(files, "attachment_status", status)
    return calls


def make(user_id=OWNER):
    user = SimpleNamespace(id=user_id, username="own", full_name="Own")
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
        get_file=AsyncMock(
            return_value=SimpleNamespace(
                download_as_bytearray=AsyncMock(return_value=bytearray(b"%PDF-1"))
            )
        ),
    )
    context = SimpleNamespace(
        bot=bot, bot_data={"is_troubleshooter": True}, user_data={"is_admin": True}
    )
    return user, context


async def press(data, user, context, text=None):
    query = SimpleNamespace(
        data=data,
        from_user=user,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(text=text, message_id=3, chat_id=user.id),
    )
    await turbine_troubleshooter.handle_button(
        SimpleNamespace(callback_query=query, effective_user=user), context
    )
    return query


@pytest.mark.asyncio
async def test_owner_saves_a_file_to_the_repo(github):
    user, context = make()

    query = await press("troubleshooter:menu_files:save:8", user, context)

    query.answer.assert_awaited_once_with("💾 Saving to the repo…")
    context.bot.get_file.assert_awaited_once_with("F8")
    url, headers, body = github.puts[0]
    assert (
        url
        == "https://api.github.com/repos/owner/host-bot/contents/app/media/pdf/safety.pdf"
    )
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert base64.b64decode(body["content"]) == b"%PDF-1"
    assert body["branch"] == "main"
    assert body["message"] == "Add pdf/safety.pdf from the troubleshooter bot"
    assert github.saved == [(8, "committed")]
    assert SETTINGS.menu["attachments"][0]["status"] == "committed"
    reply = context.bot.send_message.await_args.args
    assert reply[0] == str(OWNER) and reply[1].startswith(
        "💾 Saved pdf/safety.pdf to the repo."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "isn't valid"),
        (403, "can't write"),
        (404, "wasn't found"),
        (422, "already there"),
        (500, "Try again later"),
    ],
)
async def test_failed_saves_explain_why_and_keep_the_file_pending(
    monkeypatch, github, status, reason
):
    github.status = status
    reported = MagicMock()
    monkeypatch.setattr(files.sentry_sdk, "capture_message", reported)
    user, context = make()

    await press("troubleshooter:menu_files:save:8", user, context)

    reply = context.bot.send_message.await_args.args[1]
    assert (
        reply.startswith("⚠️ Couldn't save pdf/safety.pdf to the repo.")
        and reason in reply
    )
    assert TOKEN not in reply and TOKEN not in str(reported.call_args)
    assert github.saved == []
    assert SETTINGS.menu["attachments"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_network_errors_go_to_sentry(monkeypatch, github):
    github.error = RuntimeError("offline")
    reported = MagicMock()
    monkeypatch.setattr(files.sentry_sdk, "capture_exception", reported)
    user, context = make()

    await press("troubleshooter:menu_files:save:8", user, context)

    assert str(reported.call_args.args[0]) == "offline"
    assert "Try again later" in context.bot.send_message.await_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", ["troubleshooter:menu_files:save:9", "troubleshooter:menu_files:save:77"]
)
async def test_saved_files_are_not_sent_again(github, data):
    user, context = make()

    query = await press(data, user, context)

    query.answer.assert_awaited_once_with("Already saved.")
    assert github.puts == []


@pytest.mark.asyncio
async def test_admins_cannot_save_to_the_repo(github):
    user, context = make(ADMIN)
    context.bot_data["troubleshooter_admins"] = {ADMIN: "ann"}

    await press("troubleshooter:menu_files:save:8", user, context, text="x")

    assert github.puts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [True, False])
async def test_save_buttons_only_when_the_repo_is_set(monkeypatch, github, configured):
    if not configured:
        monkeypatch.setattr(SETTINGS, "files_repo_token", None)
    user, context = make()

    query = await press("troubleshooter:menu_files", user, context, text="x")
    text = query.edit_message_text.await_args.args[0]
    callbacks = [
        b.callback_data
        for row in query.edit_message_text.await_args.kwargs[
            "reply_markup"
        ].inline_keyboard
        for b in row
    ]

    assert ("troubleshooter:menu_files:save:8" in callbacks) is configured
    assert "troubleshooter:menu_files:send:8" in callbacks
    assert not any(c.endswith(":9") for c in callbacks)
    assert "(in the repo, live after the next deploy)" in text

    await files.send_to_owner(context, SETTINGS.menu["attachments"][0])
    markup = context.bot.send_document.await_args.kwargs["reply_markup"]
    assert (markup is not None) is configured


@pytest.mark.asyncio
async def test_start_marks_committed_files_saved_once_deployed(
    monkeypatch, tmp_path, make_cursor, patch_session
):
    import turbine_troubleshooter.db as ts

    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "safety.pdf").write_bytes(b"x")
    monkeypatch.setattr(SETTINGS, "files_dir", tmp_path)

    class Cursor(make_cursor):
        async def _fetchone(self):
            return (
                {"value": 1}
                if self.calls[-1][0].startswith("SELECT value FROM settings")
                else {"t": 1}
            )

        async def _fetchall(self):
            sql = self.calls[-1][0]
            if "FROM attachments" in sql:
                return [dict(a, status="committed") for a in attachments()[:1]]
            if "FROM menus" in sql:
                return [
                    {
                        "id": 3,
                        "parent_id": None,
                        "type": "page",
                        "title": "S",
                        "body": "",
                        "sort_order": 1,
                        "edits": None,
                    }
                ]
            return []

    async def nothing(_):
        return 0

    for name in ("menu_migrate", "io_boards_migrate", "wtgs_migrate"):
        monkeypatch.setattr(ts.schema, name, nothing)
    cur = patch_session(ts, Cursor())

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert (
        "UPDATE attachments SET status = 'saved' WHERE id IN (%s)",
        [8],
    ) in cur.calls
    assert SETTINGS.menu["attachments"][0]["status"] == "saved"
