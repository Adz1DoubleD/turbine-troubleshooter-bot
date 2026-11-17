from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    menu_node_add,
    menu_node_delete,
    menu_node_update,
)
from turbine_troubleshooter.helpers import escape_markdown, is_owner
from turbine_troubleshooter.settings import SETTINGS

from ...tools import send_notification_troubleshooter
from . import local_now
from .changes import ask_owner_to_delete

MAX_TITLE = 60
MAX_BODY = 3000
MAX_CAPTION = 1024
TO_PANEL = InlineKeyboardButton(
    "🔙 Admin Panel", callback_data="troubleshooter:admin_menu"
)
EXPIRED = "⚠️ That has expired. Start again from the Admin Panel."


def where(node_id):
    nodes = {n["id"]: n for n in SETTINGS.menu["nodes"]}
    names = []
    while node_id in nodes:
        names.insert(0, nodes[node_id]["title"])
        node_id = nodes[node_id]["parent_id"]
    return " › ".join(names) or "Main menu"


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if SETTINGS.menu is None:
        await query.answer(
            "⚠️ Menus can't be changed until they've been copied to the menu "
            "tables. Check the logs.",
            show_alert=True,
        )
        return

    nodes = SETTINGS.menu["nodes"]
    user = query.from_user
    bits = query.data.split(":")
    action = bits[1]
    draft = context.user_data.get("menu_draft") or {}
    node_id = int(bits[-1]) if bits[-1].isdigit() else draft.get("node")
    node = next((n for n in nodes if n["id"] == node_id), None)
    text, kb = EXPIRED, [[TO_PANEL]]

    if (
        action in ("menu_files", "menu_file_rm")
        or bits[2:3] == ["file"]
        or (
            query.data == "troubleshooter:menu_edit:save"
            and draft.get("field") == "file"
        )
    ):
        from .files import handle_button as handle_file_button

        await handle_file_button(update, context)
        return

    if action == "menu_manage":
        context.user_data["state"] = None
        context.user_data.pop("menu_draft", None)
        here = node["id"] if node else 0
        up = (
            InlineKeyboardButton(
                "🔙 Back",
                callback_data=f"troubleshooter:menu_manage:{node['parent_id'] or 0}",
            )
            if node
            else TO_PANEL
        )
        if node and node["type"] == "page":
            files = sum(
                a["node_id"] == node["id"] for a in SETTINGS.menu["attachments"]
            )
            body = node["body"] or ""
            text = (
                f"📋 *Edit Menus* · {escape_markdown(where(here))}\n\n📄 Page"
                + (f" · 📎 {files} file{'s' if files > 1 else ''}" if files else "")
                + (
                    f"\n\n{escape_markdown(body[:300])}"
                    + ("…" if len(body) > 300 else "")
                    if body
                    else ""
                )
            )
            kb = [
                [
                    InlineKeyboardButton(
                        "✏️ Edit", callback_data=f"troubleshooter:menu_edit:{here}"
                    ),
                    InlineKeyboardButton(
                        "🗑 Delete", callback_data=f"troubleshooter:menu_del:{here}"
                    ),
                ],
                [up],
            ]
        else:
            items = [
                InlineKeyboardButton(
                    f"{'📁' if n['type'] == 'submenu' else '📄'} {n['title']}",
                    callback_data=f"troubleshooter:menu_manage:{n['id']}",
                )
                for n in sorted(
                    nodes,
                    key=lambda n: (
                        (n["title"].lower(),)
                        if not here
                        else (n["sort_order"], n["id"])
                    ),
                )
                if (n["parent_id"] or 0) == here
            ]
            text = f"📋 *Edit Menus* · {escape_markdown(where(node and here))}\n\n" + (
                "Tap an item to change it, or add a new one here."
                if items
                else "Nothing here yet."
            )
            kb = [items[i : i + 2] for i in range(0, len(items), 2)]
            kb.append(
                [
                    InlineKeyboardButton(
                        "➕ Add Here",
                        callback_data=f"troubleshooter:menu_add:in:{here}",
                    )
                ]
                + (
                    [
                        InlineKeyboardButton(
                            "✏️ Rename",
                            callback_data=f"troubleshooter:menu_edit:{here}",
                        ),
                        InlineKeyboardButton(
                            "🗑 Delete",
                            callback_data=f"troubleshooter:menu_del:{here}",
                        ),
                    ]
                    if node
                    else []
                )
            )
            kb.append([up])

    elif action == "menu_add" and bits[2] == "in":
        parent = node["id"] if node else None
        context.user_data["menu_draft"] = {"parent": parent}
        text = (
            f"📝 *Add Content* · {escape_markdown(where(parent))}\n\n"
            "Add a page (text people read) or a submenu (a list of more buttons)?"
        )
        kb = [
            [
                InlineKeyboardButton(
                    "📄 Page", callback_data="troubleshooter:menu_add:type:page"
                ),
                InlineKeyboardButton(
                    "📁 Submenu", callback_data="troubleshooter:menu_add:type:submenu"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back", callback_data=f"troubleshooter:menu_manage:{parent or 0}"
                )
            ],
        ]

    elif action == "menu_add" and bits[2] == "type" and "parent" in draft:
        draft["type"] = bits[3]
        context.user_data["state"] = "troubleshooter:menu_add:title"
        text = (
            f"📝 *New {'page' if bits[3] == 'page' else 'submenu'}* · "
            f"{escape_markdown(where(draft['parent']))}\n\n"
            f"Type its title (up to {MAX_TITLE} characters):"
        )

    elif query.data == "troubleshooter:menu_add:save" and draft.get("title"):
        node = await menu_node_add(
            draft["parent"], draft["type"], draft["title"], draft.get("body"), user.id
        )
        nodes.append(node)
        if draft.get("file"):
            from .files import attach

            await attach(context, user, node, draft["file"])
        context.user_data.pop("menu_draft", None)
        await send_notification_troubleshooter(user, "menu_added", where(node["id"]))
        text = f"✅ *Added* · {escape_markdown(where(node['id']))}"
        kb = [
            [
                InlineKeyboardButton(
                    "👀 Open It", callback_data=f"troubleshooter:menu:{node['id']}"
                ),
                InlineKeyboardButton(
                    "📋 Edit Menus",
                    callback_data=f"troubleshooter:menu_manage:{node['id']}",
                ),
            ],
            [TO_PANEL],
        ]

    elif action == "menu_edit" and bits[2].isdigit() and node:
        text = (
            f"✏️ *Edit* · {escape_markdown(where(node['id']))}\n\n"
            "What do you want to change?"
        )
        kb = [
            [
                InlineKeyboardButton(
                    "🏷 Title",
                    callback_data=f"troubleshooter:menu_edit:title:{node['id']}",
                )
            ]
            + (
                [
                    InlineKeyboardButton(
                        "📝 Text",
                        callback_data=f"troubleshooter:menu_edit:body:{node['id']}",
                    )
                ]
                if node["type"] == "page"
                else []
            )
            + (
                [
                    InlineKeyboardButton(
                        "📎 File",
                        callback_data=f"troubleshooter:menu_edit:file:{node['id']}",
                    )
                ]
                if node["type"] == "page"
                and context.bot_data.get("is_troubleshooter")
                and SETTINGS.files_dir
                else []
            ),
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data=f"troubleshooter:menu_manage:{node['id']}",
                )
            ],
        ]

    elif action == "menu_edit" and bits[2] in ("title", "body") and node:
        field = bits[2]
        context.user_data["menu_draft"] = {"node": node["id"], "field": field}
        context.user_data["state"] = f"troubleshooter:menu_edit:{field}"
        name = "title" if field == "title" else "text"
        text = (
            f"✏️ *{name.capitalize()}* · {escape_markdown(where(node['id']))}\n\n"
            f"Now:\n{escape_markdown(node[field] or '')}\n\n"
            f"Type the new {name}. It replaces what's there now, so copy anything "
            "you want to keep."
        )
        kb = [
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=f"troubleshooter:menu_manage:{node['id']}",
                )
            ]
        ]

    elif query.data == "troubleshooter:menu_edit:save" and node and "value" in draft:
        field, value, old = draft["field"], draft["value"], node[draft["field"]]
        editor = f"@{user.username}" if user.username else user.full_name
        edited_at = local_now().strftime("%Y-%m-%d %H:%M")
        await menu_node_update(
            node["id"], field, value, user.id, editor, edited_at, old
        )
        node[field] = value
        node["edits"] = (node.get("edits") or []) + [
            {"by": editor, "at": edited_at, "changes": {field: [old, value]}}
        ]
        context.user_data.pop("menu_draft", None)
        await send_notification_troubleshooter(
            user,
            "menu_edited",
            where(node["id"]),
            message=f"Title: {old} → {value}" if field == "title" else "Text changed",
            undo=None
            if is_owner(user.id)
            else f"troubleshooter:undo:menu:{node['id']}:{len(node['edits']) - 1}",
            was=old,
        )
        text = f"✅ *Saved* · {escape_markdown(where(node['id']))}"
        kb = [
            [
                InlineKeyboardButton(
                    "👀 Open It", callback_data=f"troubleshooter:menu:{node['id']}"
                ),
                InlineKeyboardButton(
                    "📋 Edit Menus",
                    callback_data=f"troubleshooter:menu_manage:{node['id']}",
                ),
            ],
            [TO_PANEL],
        ]

    elif action == "menu_del" and node:
        back = InlineKeyboardButton(
            "❌ No, Cancel",
            callback_data=f"troubleshooter:menu_manage:{node['id']}",
        )
        owner = is_owner(user.id)
        if any(n["parent_id"] == node["id"] for n in nodes):
            await query.answer(
                "⚠️ That submenu has items in it. Delete them first.",
                show_alert=True,
            )
            return
        if len(bits) == 3:
            text = (
                f"⚠️ *Are you sure?*\n\nDelete {escape_markdown(where(node['id']))}"
                + (
                    ""
                    if owner
                    else "\n\nThe owner has to approve it before it's removed."
                )
            )
            kb = [
                [
                    back,
                    InlineKeyboardButton(
                        "✅ Yes, Delete" if owner else "✅ Yes, Ask the Owner",
                        callback_data=f"troubleshooter:menu_del:yes:{node['id']}",
                    ),
                ]
            ]
        elif not owner:
            text = await ask_owner_to_delete(
                update, context, "menu", node["id"], where(node["id"])
            )
            kb = [
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data=f"troubleshooter:menu_manage:{node['id']}",
                    )
                ]
            ]
        else:
            label = where(node["id"])
            await menu_node_delete(node["id"])
            nodes.remove(node)
            SETTINGS.menu["attachments"][:] = [
                a for a in SETTINGS.menu["attachments"] if a["node_id"] != node["id"]
            ]
            await send_notification_troubleshooter(user, "menu_deleted", label)
            text = f"✅ *Deleted* · {escape_markdown(label)}"
            kb = [
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="troubleshooter:menu_manage:"
                        f"{node['parent_id'] or 0}",
                    )
                ]
            ]

    markup = InlineKeyboardMarkup(kb)
    if query.message.text:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        context.user_data["last_msg_id"] = query.message.message_id
    else:
        sent = await context.bot.send_message(
            query.message.chat_id, text, parse_mode="Markdown", reply_markup=markup
        )
        context.user_data["last_msg_id"] = sent.message_id


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    state = context.user_data.get("state")
    draft = context.user_data.get("menu_draft") or {}
    nodes = SETTINGS.menu["nodes"] if SETTINGS.menu else []
    node = next((n for n in nodes if n["id"] == draft.get("node")), None)
    chat_id = update.effective_chat.id
    msg_id = context.user_data.get("last_msg_id")
    cancel = InlineKeyboardButton(
        "❌ Cancel",
        callback_data="troubleshooter:menu_manage:"
        f"{node['id'] if node else draft.get('parent') or 0}",
    )
    if "parent" not in draft and not node:
        context.user_data["state"] = None
        return

    parent = draft["parent"] if "parent" in draft else node["parent_id"]
    title = text if state.endswith(":title") else (node or draft)["title"]
    attached = draft.get("file") or (
        node and any(a["node_id"] == node["id"] for a in SETTINGS.menu["attachments"])
    )
    limit = MAX_CAPTION - len(f"*{title}*\n\n") if attached else MAX_BODY

    problem = None
    if state.endswith(":title"):
        taken = [
            n["title"].lower()
            for n in nodes
            if n["parent_id"] == parent and n["id"] != draft.get("node")
        ] + ([] if parent else ["io boards"])
        if not 0 < len(text) <= MAX_TITLE:
            problem = f"Keep the title between 1 and {MAX_TITLE} characters."
        elif any(c in text for c in "*_`["):
            problem = "Titles can't contain * _ ` or [."
        elif text.lower() in taken:
            problem = "Something with that title is already in that menu."
    elif len(text) > limit:
        problem = f"Keep the text to {limit} characters. It's {len(text)}."

    if problem:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"⚠️ {problem}\n\nType it again:",
            reply_markup=InlineKeyboardMarkup([[cancel]]),
        )
        return

    if state == "troubleshooter:menu_add:title" and draft.get("type") == "page":
        draft["title"] = text
        context.user_data["state"] = "troubleshooter:menu_add:body"
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"📝 *{title}*\n\nNow type the text for the page"
            + (
                ", or send a PDF or photo. Text sent with it becomes its caption."
                if context.bot_data.get("is_troubleshooter") and SETTINGS.files_dir
                else ":"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[cancel]]),
        )
        return

    if state == "troubleshooter:menu_add:title":
        draft["title"] = text
    elif state == "troubleshooter:menu_add:body":
        draft["body"] = text
    else:
        draft["value"] = text

    if node:
        body = text if draft["field"] == "body" else node["body"]
        save = "troubleshooter:menu_edit:save"
        is_page = node["type"] == "page"
    else:
        body = draft.get("body")
        save = "troubleshooter:menu_add:save"
        is_page = draft["type"] == "page"

    context.user_data["state"] = None
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Save", callback_data=save), cancel]]
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"👀 *Preview*\n\n*{title}*\n\n"
            + (body or "" if is_page else "📁 Submenu")
            + {"photo": "\n\n📎 Photo attached", "document": "\n\n📎 PDF attached"}.get(
                (draft.get("file") or {}).get("type"), ""
            ),
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except BadRequest as e:
        if "parse" not in str(e).lower():
            raise
        context.user_data["state"] = state
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text="⚠️ Telegram can't show that formatting. There's probably an "
            "unclosed * or _ in it. Fix it and send it again:",
            reply_markup=InlineKeyboardMarkup([[cancel]]),
        )
