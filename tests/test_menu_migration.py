import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import turbine_troubleshooter.db as ts
from turbine_troubleshooter.settings import SETTINGS
from turbine_troubleshooter.tools import get_troubleshooter_content

MADE_UP_MENU = {
    "Safety": "Wear the *harness*.",
    "Électrique": {
        "menu": {
            "Diagrams": {
                "menu": {
                    "Overview": {"text": "Main overview", "document": "file:pdf/o.pdf"},
                    "Cabinet": {"text": "Cabinet photo", "photo": "file:img/c.jpg"},
                    "Empty": {"menu": {}},
                }
            },
            "Breakers_1": {"text": "Reset with care."},
        }
    },
    "Contacts": {"menu": {"Control room": "Call 0000"}},
    "Manuals": {
        "text": "Both parts",
        "document": ["file:pdf/m1.pdf", "file:pdf/m2.pdf"],
    },
}


def migrate_cursor(make_cursor, fetchone=(None, None, None)):
    class Cursor(make_cursor):
        async def _execute(self, *args):
            await super()._execute(*args)
            if args[0].startswith("INSERT INTO menus"):
                self.lastrowid += 1

    return Cursor(fetchone=list(fetchone), lastrowid=0)


def inserted(cur, table):
    return [c[1] for c in cur.calls if c[0].startswith(f"INSERT INTO {table}")]


def screens(content):
    def path(key):
        item = content[key]
        return (
            (*path(item["parent"]), item["title"])
            if item.get("parent")
            else (item["title"],)
        )

    return {
        path(k): (
            item["type"],
            item.get("content"),
            item.get("file"),
            [path(c) for c in item.get("items", [])],
        )
        for k, item in content.items()
    }, [path(k) for k, item in content.items() if not item.get("parent")]


def menu_from(cur):
    return {
        "nodes": [
            dict(
                zip(
                    ("id", "parent_id", "type", "title", "body", "sort_order"),
                    (i, *row[:5]),
                )
            )
            for i, row in enumerate(inserted(cur, "menus"), 1)
        ],
        "attachments": [
            {
                "node_id": a[0],
                "type": a[1],
                "path": a[2],
                "file_id": None,
                "status": "saved",
            }
            for a in inserted(cur, "attachments")
        ],
    }


@pytest.mark.asyncio
async def test_menus_built_from_rows_match_the_json(
    monkeypatch, tmp_path, make_cursor, patch_session
):
    monkeypatch.setattr(SETTINGS, "files_dir", tmp_path)
    cur = patch_session(ts, migrate_cursor(make_cursor))
    count = await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    monkeypatch.setattr(
        SETTINGS,
        "content",
        SimpleNamespace(MODULES_MAP=ts.content_from_json(json.dumps(MADE_UP_MENU))),
    )
    from_json = get_troubleshooter_content()
    monkeypatch.setattr(SETTINGS, "menu", menu_from(cur))
    from_rows = get_troubleshooter_content()

    assert count == 10
    assert len(from_rows) == len(from_json) == 10
    assert screens(from_rows) == screens(from_json)
    assert all(
        k.startswith("troubleshooter:menu:")
        for k in from_rows
        if k != "troubleshooter:ioboard"
    )


@pytest.mark.asyncio
async def test_copy_keeps_order_nesting_owner_and_legacy_keys(
    monkeypatch, make_cursor, patch_session
):
    monkeypatch.setattr(SETTINGS, "owner_id", "42")
    cur = patch_session(ts, migrate_cursor(make_cursor))

    await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    rows = inserted(cur, "menus")
    assert [(r[0], r[2], r[4]) for r in rows[:4]] == [
        (None, "Safety", 1),
        (None, "Électrique", 2),
        (None, "Contacts", 3),
        (None, "Manuals", 4),
    ]
    assert rows[4][:3] == (2, "submenu", "Diagrams")
    assert all(r[5] == r[6] == 42 for r in rows)
    assert json.loads(rows[7][7]) == ["Électrique", "Diagrams", "Overview"]
    assert inserted(cur, "attachments") == [
        (4, "document", "pdf/m1.pdf", 1, 42),
        (4, "document", "pdf/m2.pdf", 2, 42),
        (8, "document", "pdf/o.pdf", 1, 42),
        (9, "photo", "img/c.jpg", 1, 42),
    ]


@pytest.mark.asyncio
async def test_copy_is_one_transaction_marked_done_inside_it(
    make_cursor, patch_session
):
    cur = patch_session(ts, migrate_cursor(make_cursor))

    await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    sql = [c[0] for c in cur.calls]
    start = sql.index("START TRANSACTION")
    assert sql[-1] == "COMMIT"
    assert cur.calls[-2] == (
        "INSERT INTO settings (name, value) VALUES (%s, 1)",
        (ts.MENU_MIGRATED,),
    )
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in sql[:start])


@pytest.mark.asyncio
async def test_copy_runs_only_once(make_cursor, patch_session):
    cur = patch_session(
        ts, migrate_cursor(make_cursor, [{"t": 1}, {"t": 1}, {"value": 1}])
    )

    assert await ts.menu_migrate(json.dumps(MADE_UP_MENU)) == 0

    assert not any(c[0].startswith(("INSERT", "START", "CREATE")) for c in cur.calls)


@pytest.mark.asyncio
async def test_new_database_starts_with_empty_menus(make_cursor, patch_session):
    cur = patch_session(ts, migrate_cursor(make_cursor))

    assert await ts.menu_migrate(None) == 0

    assert inserted(cur, "menus") == []
    assert inserted(cur, "settings") == [(ts.MENU_MIGRATED,)]
    assert not any(c[0] == "START TRANSACTION" for c in cur.calls)


@pytest.mark.asyncio
async def test_failed_copy_is_rolled_back(make_cursor, patch_session):
    cur = patch_session(ts, migrate_cursor(make_cursor))
    real = cur._execute

    async def fail_on_photo(*args):
        await real(*args)
        if args[0].startswith("INSERT INTO attachments") and args[1][1] == "photo":
            raise RuntimeError("disk full")

    cur.execute.side_effect = fail_on_photo

    with pytest.raises(RuntimeError, match="disk full"):
        await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    sql = [c[0] for c in cur.calls]
    assert sql[-1] == "ROLLBACK"
    assert "COMMIT" not in sql
    assert not any(s.startswith("INSERT INTO settings") for s in sql)


@pytest.mark.asyncio
async def test_failed_copy_does_not_stop_the_bot_loading(
    monkeypatch, make_cursor, patch_session
):
    reported = MagicMock()
    monkeypatch.setattr(ts.schema.sentry_sdk, "capture_exception", reported)

    async def broken(_):
        raise RuntimeError("no space")

    monkeypatch.setattr(ts.schema, "menu_migrate", broken)
    cur = make_cursor(
        fetchone=[{"t": "content"}, {"t": "codes"}, {"t": "users"}, {"t": "parts"}],
        fetchall=[[], [{"id": 1, "code": "E1", "advice": "a", "parts": "p"}]],
    )
    patch_session(ts, cur)
    app = SimpleNamespace(bot_data={})

    await ts.init_troubleshooter_db(app)

    assert "E1" in app.bot_data["codes"]
    assert str(reported.call_args.args[0]) == "no space"


@pytest.mark.asyncio
async def test_startup_copies_the_stored_menu(monkeypatch, make_cursor, patch_session):
    seen = []

    async def record(data):
        seen.append(data)
        return 0

    monkeypatch.setattr(ts.schema, "menu_migrate", record)
    stored = json.dumps({"Note": "Hi"})
    cur = make_cursor(
        fetchone=[{"t": "content"}, {"t": "codes"}, {"t": "users"}, {"t": "parts"}],
        fetchall=[[{"name": "MODULES_MAP", "data": stored}]],
    )
    patch_session(ts, cur)

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert seen == [stored]


@pytest.mark.asyncio
@pytest.mark.parametrize("copied", [True, False])
async def test_rows_are_used_only_once_the_copy_is_done(
    monkeypatch, make_cursor, patch_session, copied
):
    node = {"id": 1, "parent_id": None, "type": "page", "title": "Note"}

    class Cursor(make_cursor):
        async def _fetchone(self):
            if self.calls[-1][0].startswith("SELECT value FROM settings"):
                return {"value": 1} if copied else None
            return {"t": 1}

        async def _fetchall(self):
            return [node] if "FROM menus" in self.calls[-1][0] else []

    async def nothing_to_copy(_):
        return 0

    monkeypatch.setattr(ts.schema, "menu_migrate", nothing_to_copy)
    patch_session(ts, Cursor())

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert SETTINGS.menu == (
        {"nodes": [{**node, "edits": []}], "attachments": []} if copied else None
    )


@pytest.mark.asyncio
async def test_tapping_through_a_menu_built_from_rows(monkeypatch):
    import turbine_troubleshooter

    monkeypatch.setattr(
        SETTINGS,
        "menu",
        {
            "nodes": [
                {
                    "id": 5,
                    "parent_id": None,
                    "type": "submenu",
                    "title": "Torque",
                    "body": None,
                    "sort_order": 1,
                },
                {
                    "id": 7,
                    "parent_id": 5,
                    "type": "page",
                    "title": "Tower",
                    "body": "tower text",
                    "sort_order": 2,
                },
                {
                    "id": 6,
                    "parent_id": 5,
                    "type": "page",
                    "title": "Hub",
                    "body": "hub text",
                    "sort_order": 1,
                },
            ],
            "attachments": [],
        },
    )
    edits = []

    async def edit_message_text(text, **kwargs):
        edits.append(
            (
                text,
                [
                    b.callback_data
                    for row in kwargs["reply_markup"].inline_keyboard
                    for b in row
                ],
            )
        )

    for data in ("troubleshooter:menu:5", "troubleshooter:menu:6"):
        query = SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(text="menu"),
            edit_message_text=edit_message_text,
        )
        await turbine_troubleshooter.handle_button(
            SimpleNamespace(callback_query=query),
            SimpleNamespace(bot_data={}, user_data={"is_admin": False}),
        )

    assert edits == [
        (
            "*Torque*\n\nSelect an option:",
            ["troubleshooter:menu:6", "troubleshooter:menu:7", "troubleshooter:home"],
        ),
        ("*Hub*\n\nhub text", ["troubleshooter:menu:5"]),
    ]


@pytest.mark.asyncio
async def test_an_old_menu_button_says_it_is_out_of_date():
    from unittest.mock import AsyncMock

    import turbine_troubleshooter

    query = SimpleNamespace(
        data="troubleshooter:torque:hub",
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )

    await turbine_troubleshooter.handle_button(
        SimpleNamespace(callback_query=query),
        SimpleNamespace(bot_data={}, user_data={}),
    )

    query.answer.assert_awaited_once_with(
        "This button is out of date. Send /start for the latest menu.",
        show_alert=True,
    )
