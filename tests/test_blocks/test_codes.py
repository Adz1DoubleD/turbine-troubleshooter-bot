from datetime import datetime
from types import SimpleNamespace

import pytest

from troubleshooter.blocks import codes

CODE = {
    "id": 2,
    "code": "14040",
    "advice": "Check the fuse",
    "parts": "Fuse 5A",
}


@pytest.fixture(autouse=True)
def neighbours(monkeypatch):
    calls = []

    async def fake_neighbours(row_id, table, order_by=None):
        calls.append((row_id, table, order_by))
        return 1, 3

    monkeypatch.setattr(codes, "get_neighbours", fake_neighbours)
    return calls


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def make_query_update(data):
    edits = []

    async def edit_message_text(text, **kwargs):
        edits.append({"text": text, **kwargs})

    query = SimpleNamespace(
        data=data,
        message=SimpleNamespace(message_id=55),
        edit_message_text=edit_message_text,
    )
    return SimpleNamespace(callback_query=query), edits


def search_context(code_list=None, is_admin=False, last_msg_id=9):
    record = {"edits": [], "actions": []}

    async def edit_message_text(**kwargs):
        record["edits"].append(kwargs)

    async def send_chat_action(chat_id, action):
        record["actions"].append(action)

    context = SimpleNamespace(
        bot=SimpleNamespace(
            edit_message_text=edit_message_text, send_chat_action=send_chat_action
        ),
        user_data={
            "state": "troubleshooter:code_search",
            "last_msg_id": last_msg_id,
            "is_admin": is_admin,
        },
        bot_data={
            "codes": {c["code"]: c for c in (code_list or [dict(CODE)])},
            "is_troubleshooter": True,
        },
    )
    return context, record


UPDATE = SimpleNamespace(effective_chat=SimpleNamespace(id=1))


@pytest.mark.asyncio
async def test_code_view_shows_code_and_paging(neighbours):
    text, markup = await codes.code_view(dict(CODE), admin=False)

    assert "`14040`" in text
    assert "Check the fuse" in text
    assert "Fuse 5A" in text
    assert neighbours == [(2, "codes", "code")]
    assert callbacks(markup) == [
        "troubleshooter:code_search:1",
        "troubleshooter:code_search",
        "troubleshooter:code_search:3",
        "back:troubleshooter",
    ]


@pytest.mark.asyncio
async def test_code_view_blank_buttons_at_ends(monkeypatch):
    async def no_neighbours(*args, **kwargs):
        return None, None

    monkeypatch.setattr(codes, "get_neighbours", no_neighbours)

    _, markup = await codes.code_view(dict(CODE), admin=False)

    first_row = markup.inline_keyboard[0]
    assert [b.callback_data for b in first_row] == [
        "ignore",
        "troubleshooter:code_search",
        "ignore",
    ]


@pytest.mark.asyncio
async def test_code_view_without_id_skips_neighbours(neighbours):
    code = {k: v for k, v in CODE.items() if k != "id"}

    _, markup = await codes.code_view(code, admin=False)

    assert neighbours == []
    assert callbacks(markup)[0] == "ignore"


@pytest.mark.asyncio
@pytest.mark.parametrize("admin,shown", [(True, True), (False, False)])
async def test_code_view_admin_buttons(admin, shown):
    _, markup = await codes.code_view(dict(CODE), admin=admin)

    cbs = callbacks(markup)
    assert ("troubleshooter:code_edit:14040" in cbs) is shown
    assert ("troubleshooter:code_confirm_del:14040" in cbs) is shown


@pytest.mark.asyncio
async def test_code_view_added_and_edited_by():
    code = dict(
        CODE,
        added_by="@ed_itor",
        added_at=datetime(2026, 1, 5, 9, 30),
        edits=[{"by": f"@user{i}", "at": "2026-02-0%d 10:00" % i} for i in range(1, 6)],
    )

    text, _ = await codes.code_view(code, admin=False)

    assert "*Added by:* @ed\\_itor (05 Jan 2026)" in text
    assert "@user3 (03 Feb 2026), @user4 (04 Feb 2026), @user5 (05 Feb 2026)" in text
    assert "@user1" not in text
    assert "+2 more" in text


@pytest.mark.asyncio
async def test_code_view_no_meta_when_unknown():
    text, _ = await codes.code_view(dict(CODE), admin=False)

    assert "Added by" not in text
    assert "Edited by" not in text


@pytest.mark.asyncio
async def test_button_search_sets_state():
    update, edits = make_query_update("troubleshooter:code_search")
    context = SimpleNamespace(user_data={}, bot_data={})

    await codes.button_search(update, context)

    assert context.user_data["state"] == "troubleshooter:code_search"
    assert context.user_data["last_msg_id"] == 55
    assert "Fault Code Search" in edits[0]["text"]


@pytest.mark.asyncio
async def test_button_page_shows_code_by_id():
    update, edits = make_query_update("troubleshooter:code_search:2")
    context = SimpleNamespace(user_data={}, bot_data={"codes": {"14040": dict(CODE)}})

    await codes.button_page(update, context)

    assert "`14040`" in edits[0]["text"]


@pytest.mark.asyncio
async def test_button_page_missing_code_goes_back_to_search():
    update, edits = make_query_update("troubleshooter:code_search:99")
    context = SimpleNamespace(user_data={}, bot_data={"codes": {"14040": dict(CODE)}})

    await codes.button_page(update, context)

    assert context.user_data["state"] == "troubleshooter:code_search"
    assert "Fault Code Search" in edits[0]["text"]


@pytest.mark.asyncio
async def test_handle_search_exact_match_shows_code():
    context, record = search_context()

    await codes.handle_search(UPDATE, context, " 14040 ")

    assert context.user_data["state"] is None
    assert record["actions"] == ["typing"]
    assert record["edits"][0]["message_id"] == 9
    assert "`14040`" in record["edits"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin,add_shown", [(True, True), (False, False)])
async def test_handle_search_suggestions(monkeypatch, is_admin, add_shown):
    found = []

    def fake_find(text, code_data):
        found.append(text)
        return [dict(CODE)]

    monkeypatch.setattr(codes, "find_codes", fake_find)
    context, record = search_context(is_admin=is_admin)

    await codes.handle_search(UPDATE, context, "140")

    edit = record["edits"][0]
    assert found == ["140"]
    assert "No exact match" in edit["text"]
    cbs = callbacks(edit["reply_markup"])
    assert cbs[0] == "troubleshooter:code_search:2"
    assert "🔧 14040" in labels(edit["reply_markup"])
    assert ("troubleshooter:code_add" in cbs) is add_shown
    assert cbs[-1] == "back:troubleshooter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_admin,expected",
    [
        (
            True,
            [
                "troubleshooter:code_search",
                "troubleshooter:code_add",
                "back:troubleshooter",
            ],
        ),
        (False, ["troubleshooter:code_search", "back:troubleshooter"]),
    ],
)
async def test_handle_search_not_found(monkeypatch, is_admin, expected):
    monkeypatch.setattr(codes, "find_codes", lambda text, code_data: [])
    context, record = search_context(is_admin=is_admin)

    await codes.handle_search(UPDATE, context, "9_99")

    edit = record["edits"][0]
    assert "Code Not Found" in edit["text"]
    assert "9\\_99" in edit["text"]
    assert callbacks(edit["reply_markup"]) == expected


@pytest.mark.asyncio
async def test_handle_search_without_message_id_replies(monkeypatch):
    monkeypatch.setattr(codes, "find_codes", lambda text, code_data: [])
    context, record = search_context(last_msg_id=None)
    replies = []

    async def reply_text(text, **kwargs):
        replies.append(text)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(reply_text=reply_text),
    )

    await codes.handle_search(update, context, "nope")

    assert record["edits"] == []
    assert "Code Not Found" in replies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "advice, shown",
    [
        ("Connected to BILL_ENC_A on HM", "Connected to BILL\\_ENC\\_A on HM"),
        ("Connected to PWM_A on Hub Module", "Connected to PWM\\_A on Hub Module"),
        ("***Seek advice first***", "\\*\\*\\*Seek advice first\\*\\*\\*"),
        ("Trip from Delta`s", "Trip from Delta\\`s"),
    ],
    ids=["signal-name", "lone-underscore", "asterisks", "backtick"],
)
async def test_code_view_escapes_advice(advice, shown):
    text, _ = await codes.code_view(dict(CODE, advice=advice), admin=False)

    assert f"*Advice:*\n{shown}\n" in text


@pytest.mark.asyncio
async def test_code_view_escapes_parts_and_handles_empty():
    text, _ = await codes.code_view(dict(CODE, parts="PN_123"), admin=False)
    assert "*Parts:*\nPN\\_123" in text

    text, _ = await codes.code_view(dict(CODE, advice=None, parts=None), admin=False)
    assert "*Advice:*\n\n" in text
    assert text.rstrip().endswith("*Parts:*")
