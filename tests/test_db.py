from datetime import datetime
from types import SimpleNamespace

import pytest

import troubleshooter.db as ts


@pytest.mark.asyncio
async def test_fault_code_add_success(make_cursor, patch_session):
    cur = make_cursor(fetchone=[{"id": 42}])
    patch_session(ts, cur)
    assert await ts.fault_code_add(code="E1", advice="check", parts="sensor") == 42
    assert cur.execute.call_args_list[0].args[1] == {
        "code": "E1",
        "advice": "check",
        "parts": "sensor",
        "added_by": None,
        "added_at": None,
        "edited_by": None,
        "edited_at": None,
    }


@pytest.mark.asyncio
async def test_fault_code_add_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.fault_code_add(code="E1")


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount,expected", [(1, True), (0, False)])
async def test_delete_entry_result(make_cursor, patch_session, rowcount, expected):
    cur = make_cursor(rowcount=rowcount)
    patch_session(ts, cur)
    assert await ts.delete_entry("codes", "code", "E1") is expected
    assert "DELETE FROM `codes` WHERE `code` = %s" in cur.execute.call_args.args[0]
    assert cur.execute.call_args.args[1] == ("E1",)


@pytest.mark.asyncio
async def test_delete_entry_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.delete_entry("parts", "id", 7)


@pytest.mark.asyncio
async def test_part_add_returns_new_id(make_cursor, patch_session):
    cur = make_cursor(rowcount=1)
    cur.lastrowid = 42
    patch_session(ts, cur)
    assert await ts.part_add("PN123", "New pump") == 42
    assert cur.execute.call_args.args[1] == ("PN123", "New pump", "", None)


@pytest.mark.asyncio
async def test_part_add_duplicate_returns_none(make_cursor, patch_session):
    cur = make_cursor(rowcount=0)
    patch_session(ts, cur)
    assert await ts.part_add("PN123", "New pump") is None


@pytest.mark.asyncio
async def test_part_add_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.part_add("PN123", "New pump")


@pytest.mark.asyncio
async def test_admin_add_success_with_optional_username(make_cursor, patch_session):
    cur = make_cursor()
    patch_session(ts, cur)
    await ts.admin_add(123, "tester")
    assert cur.execute.call_args.args[1] == {"user_id": 123, "username": "tester"}


@pytest.mark.asyncio
async def test_admin_add_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.admin_add(123)


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount,expected", [(1, True), (0, False)])
async def test_admin_remove_result(make_cursor, patch_session, rowcount, expected):
    cur = make_cursor(rowcount=rowcount)
    patch_session(ts, cur)
    assert await ts.admin_remove(123) is expected


@pytest.mark.asyncio
async def test_admin_remove_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.admin_remove(123)


@pytest.mark.asyncio
async def test_user_add_new_user_inserts_and_returns_true(make_cursor, patch_session):
    cur = make_cursor(fetchone=[None])
    patch_session(ts, cur)
    assert await ts.user_add(123, "bob") is True
    insert = cur.execute.call_args_list[1]
    assert "INSERT INTO users" in insert.args[0]
    assert insert.args[1] == (123, "bob")


@pytest.mark.asyncio
async def test_user_add_existing_user_updates_and_returns_false(
    make_cursor, patch_session
):
    cur = make_cursor(fetchone=[{"user_id": 123}])
    patch_session(ts, cur)
    assert await ts.user_add(123, "bob") is False
    update = cur.execute.call_args_list[1]
    assert "UPDATE users" in update.args[0]
    assert update.args[1] == ("bob", 123)


@pytest.mark.asyncio
async def test_users_get_maps_and_casts(make_cursor, patch_session):
    cur = make_cursor(
        fetchall=[
            [
                {
                    "user_id": "123",
                    "username": "bob",
                    "is_admin": "1",
                    "last_login": "T",
                    "notifications_enabled": "0",
                },
                {"user_id": 456, "username": None, "is_admin": 0, "last_login": None},
            ]
        ]
    )
    patch_session(ts, cur)
    assert await ts.users_get() == [
        {
            "user_id": 123,
            "username": "bob",
            "is_admin": 1,
            "last_login": "T",
            "notifications_enabled": 0,
            "is_approved": 0,
        },
        {
            "user_id": 456,
            "username": None,
            "is_admin": 0,
            "last_login": None,
            "notifications_enabled": 1,
            "is_approved": 0,
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("row,expected", [({"notifications_enabled": 0}, 0), (None, 1)])
async def test_user_notifications_get(make_cursor, patch_session, row, expected):
    cur = make_cursor(fetchone=[row])
    patch_session(ts, cur)
    assert await ts.user_notifications_get(123) == expected
    assert cur.execute.call_args.args[1] == (123,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row,expected", [({"notifications_enabled": 0}, 0), (None, None)]
)
async def test_user_notifications_toggle(make_cursor, patch_session, row, expected):
    cur = make_cursor(fetchone=[row])
    patch_session(ts, cur)

    assert await ts.user_notifications_toggle(123) == expected

    update = cur.execute.call_args_list[0]
    assert "UPDATE users" in update.args[0]
    assert "1 - notifications_enabled" in update.args[0]
    assert update.args[1] == (123,)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["part_no", "description", "section"])
async def test_part_update_success(make_cursor, patch_session, field):
    cur = make_cursor(rowcount=1)
    patch_session(ts, cur)
    assert await ts.part_update(7, field, "new value") is True
    assert (
        f"UPDATE parts SET `{field}` = %s WHERE id = %s"
        in cur.execute.call_args.args[0]
    )
    assert cur.execute.call_args.args[1] == ("new value", 7)


@pytest.mark.asyncio
async def test_part_update_rejects_unknown_field(make_cursor, patch_session):
    cur = make_cursor()
    patch_session(ts, cur)
    with pytest.raises(ValueError):
        await ts.part_update(7, "id = 1; DROP TABLE parts; --", "x")
    cur.execute.assert_not_called()


@pytest.mark.asyncio
async def test_part_update_db_error_raises(make_cursor, patch_session):
    cur = make_cursor(error=RuntimeError("offline"))
    patch_session(ts, cur)
    with pytest.raises(RuntimeError, match="offline"):
        await ts.part_update(7, "description", "x")


@pytest.mark.asyncio
async def test_fault_code_add_passes_times_and_editor(make_cursor, patch_session):
    cur = make_cursor(fetchone=[{"id": 42}])
    patch_session(ts, cur)
    added_at = datetime(2026, 7, 2, 0, 30)

    await ts.fault_code_add(
        code="E1",
        added_by="@alice",
        added_at=added_at,
        edited_by="@bob",
        edited_at="2026-07-02 00:30",
    )

    sql, params = cur.execute.call_args_list[0].args
    assert "COALESCE(%(added_at)s, NOW())" in sql
    assert "COALESCE(%(edited_at)s" in sql
    assert params["added_at"] == added_at
    assert params["edited_by"] == "@bob"
    assert params["edited_at"] == "2026-07-02 00:30"


@pytest.mark.asyncio
async def test_fault_code_add_editor_defaults_to_adder(make_cursor, patch_session):
    cur = make_cursor(fetchone=[{"id": 42}])
    patch_session(ts, cur)

    await ts.fault_code_add(code="E1", added_by="@alice")

    assert cur.execute.call_args_list[0].args[1]["edited_by"] == "@alice"


@pytest.mark.asyncio
async def test_part_add_saves_who_added_it(make_cursor, patch_session):
    cur = make_cursor(rowcount=1)
    cur.lastrowid = 42
    patch_session(ts, cur)

    assert await ts.part_add("PN123", "New pump", added_by="@alice") == 42
    sql, params = cur.execute.call_args.args
    assert "added_by" in sql
    assert params == ("PN123", "New pump", "", "@alice")


@pytest.mark.asyncio
async def test_part_update_with_editor_appends_history(make_cursor, patch_session):
    cur = make_cursor(rowcount=1)
    patch_session(ts, cur)

    assert (
        await ts.part_update(7, "description", "new", "@bob", "2026-07-02 00:30")
        is True
    )
    sql, params = cur.execute.call_args.args
    assert "`description` = %s" in sql
    assert "JSON_ARRAY_APPEND" in sql
    assert params == ("new", "@bob", "2026-07-02 00:30", 7)


def test_uses_its_own_database_when_set(monkeypatch):
    import importlib

    monkeypatch.setenv("TROUBLESHOOTER_DB_URL", "mysql://u:p@ts-host:3306/tsdb")
    monkeypatch.setenv("JAWSDB_URL", "mysql://u:p@main-host:3306/maindb")
    own = importlib.reload(ts).db_url

    monkeypatch.delenv("TROUBLESHOOTER_DB_URL")
    fallback = importlib.reload(ts).db_url

    monkeypatch.undo()
    importlib.reload(ts)

    assert (own.hostname, own.path) == ("ts-host", "/tsdb")
    assert (fallback.hostname, fallback.path) == ("main-host", "/maindb")


@pytest.mark.asyncio
async def test_export_only_reads_troubleshooter_tables(make_cursor, patch_session):
    cur = make_cursor()
    patch_session(ts, cur)

    assert await ts.db_tables("pairs") is None
    cur.execute.assert_not_called()


def content_rows(**items):
    import json

    return [{"name": k, "data": json.dumps(v)} for k, v in items.items()]


FULL_CONTENT = {
    "MODULES_MAP": {
        "Diagrams": {"menu": {"SLD": {"text": " ", "document": "file:pdf/SLD.pdf"}}}
    },
    "WTG_MAP": {"WTA01": 1},
    "IO_BOARDS": {"io1": "IO Board 1"},
    "PART_ACCESSORIES": ["bolt"],
}


@pytest.mark.asyncio
async def test_content_is_loaded_from_the_database(
    monkeypatch, make_cursor, patch_session
):
    from pathlib import Path

    from troubleshooter.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "files_dir", Path("/media"))
    cur = make_cursor(
        fetchone=[{"t": "codes"}, {"t": "users"}, {"t": "parts"}, {"t": "io1"}],
        fetchall=[content_rows(**FULL_CONTENT), [], [], [], [], []],
    )
    patch_session(ts, cur)

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    sld = SETTINGS.content.MODULES_MAP["Diagrams"]["menu"]["SLD"]["document"]
    assert sld == Path("/media") / "pdf/SLD.pdf"
    assert SETTINGS.content.WTG_MAP == {"WTA01": 1}
    assert SETTINGS.content.IO_BOARDS == {"io1": "IO Board 1"}


@pytest.mark.parametrize(
    "rows",
    [[], content_rows(WTG_MAP={"WTA01": 1})],
    ids=["empty-table", "incomplete"],
)
@pytest.mark.asyncio
async def test_content_falls_back_to_setup_when_table_incomplete(
    monkeypatch, make_cursor, patch_session, rows
):
    from troubleshooter.settings import SETTINGS

    original = SETTINGS.content
    monkeypatch.setattr(SETTINGS.content, "IO_BOARDS", {})
    cur = make_cursor(
        fetchone=[{"t": "codes"}, {"t": "users"}, {"t": "parts"}],
        fetchall=[rows, [], [], [], []],
    )
    patch_session(ts, cur)

    await ts.init_troubleshooter_db(SimpleNamespace(bot_data={}))

    assert SETTINGS.content is original


def test_content_from_json_resolves_only_file_references(monkeypatch):
    from pathlib import Path

    from troubleshooter.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "files_dir", "/media")
    data = '{"a": "file:images/m.png", "b": ["plain text", "file:pdf/x.pdf"], "c": 3}'

    assert ts.content_from_json(data) == {
        "a": Path("/media") / "images/m.png",
        "b": ["plain text", Path("/media") / "pdf/x.pdf"],
        "c": 3,
    }


def test_missing_file_is_reported(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from troubleshooter.settings import SETTINGS

    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "there.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(SETTINGS, "files_dir", tmp_path)
    reported = MagicMock()
    monkeypatch.setattr(ts.sentry_sdk, "capture_message", reported)

    ts.content_from_json('["file:pdf/there.pdf", "file:pdf/gone.pdf"]')

    reported.assert_called_once()
    assert "pdf/gone.pdf" in reported.call_args.args[0]


@pytest.mark.asyncio
async def test_no_content_anywhere_gives_empty_menus(
    monkeypatch, make_cursor, patch_session
):
    from unittest.mock import MagicMock

    from troubleshooter.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "content", None)
    reported = MagicMock()
    monkeypatch.setattr(ts.sentry_sdk, "capture_message", reported)
    cur = make_cursor(
        fetchone=[{"t": "codes"}, {"t": "users"}, {"t": "parts"}],
        fetchall=[
            [],
            [{"id": 1, "code": "E1", "advice": "a", "parts": "p"}],
            [],
            [],
            [],
        ],
    )
    patch_session(ts, cur)
    app = SimpleNamespace(bot_data={})

    await ts.init_troubleshooter_db(app)

    assert SETTINGS.content.MODULES_MAP == {}
    assert SETTINGS.content.IO_BOARDS == {}
    assert "E1" in app.bot_data["codes"]
    assert "missing" in reported.call_args.args[0]
