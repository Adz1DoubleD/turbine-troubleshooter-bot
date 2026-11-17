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
}


def migrate_cursor(make_cursor, fetchone=(None, None, None)):
    class Cursor(make_cursor):
        async def _execute(self, *args):
            await super()._execute(*args)
            if args[0].startswith("INSERT INTO menu_nodes"):
                self.lastrowid += 1

    return Cursor(fetchone=list(fetchone), lastrowid=0)


def inserted(cur, table):
    return [c[1] for c in cur.calls if c[0].startswith(f"INSERT INTO {table}")]


@pytest.mark.asyncio
async def test_menus_built_from_rows_match_the_json(
    monkeypatch, tmp_path, make_cursor, patch_session
):
    monkeypatch.setattr(SETTINGS, "files_dir", tmp_path)
    monkeypatch.setattr(SETTINGS, "owner_id", "42")
    cur = patch_session(ts, migrate_cursor(make_cursor))

    count = await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    nodes = {
        i: dict(zip(("parent", "type", "title", "body", "order"), row[:5]))
        for i, row in enumerate(inserted(cur, "menu_nodes"), 1)
    }
    files = {node: (kind, path) for node, kind, path, _ in inserted(cur, "attachments")}

    def build(parent):
        tree = {}
        for i in sorted(
            (i for i, n in nodes.items() if n["parent"] == parent),
            key=lambda i: nodes[i]["order"],
        ):
            n = nodes[i]
            if n["type"] == "submenu":
                tree[n["title"]] = {"menu": build(i)}
            elif i in files:
                tree[n["title"]] = {
                    "text": n["body"],
                    files[i][0]: tmp_path / files[i][1],
                }
            else:
                tree[n["title"]] = n["body"]
        return tree

    monkeypatch.setattr(
        SETTINGS,
        "content",
        SimpleNamespace(MODULES_MAP=ts.content_from_json(json.dumps(MADE_UP_MENU))),
    )
    from_json = get_troubleshooter_content()
    monkeypatch.setattr(SETTINGS, "content", SimpleNamespace(MODULES_MAP=build(None)))
    from_rows = get_troubleshooter_content()

    assert count == len(nodes) == 9
    assert list(from_rows.items()) == list(from_json.items())


@pytest.mark.asyncio
async def test_copy_keeps_order_nesting_owner_and_legacy_keys(
    monkeypatch, make_cursor, patch_session
):
    monkeypatch.setattr(SETTINGS, "owner_id", "42")
    cur = patch_session(ts, migrate_cursor(make_cursor))

    await ts.menu_migrate(json.dumps(MADE_UP_MENU))

    rows = inserted(cur, "menu_nodes")
    assert [(r[0], r[2], r[4]) for r in rows[:3]] == [
        (None, "Safety", 1),
        (None, "Électrique", 2),
        (None, "Contacts", 3),
    ]
    assert rows[3][:3] == (2, "submenu", "Diagrams")
    assert all(r[5] == r[6] == 42 for r in rows)
    assert json.loads(rows[6][7]) == ["Électrique", "Diagrams", "Overview"]
    assert inserted(cur, "attachments") == [
        (7, "document", "pdf/o.pdf", 42),
        (8, "photo", "img/c.jpg", 42),
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
async def test_nothing_to_copy_without_a_menu(make_cursor, patch_session):
    cur = patch_session(ts, migrate_cursor(make_cursor))

    assert await ts.menu_migrate(None) == 0

    assert not any(c[0].startswith(("INSERT", "START")) for c in cur.calls)


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
