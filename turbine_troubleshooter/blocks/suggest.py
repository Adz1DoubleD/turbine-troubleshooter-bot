import html
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import turbine_troubleshooter

from ..db import content_save, suggestion_add, suggestion_remove
from ..helpers import escape_markdown, is_owner
from ..settings import SETTINGS
from ..tools import get_troubleshooter_content

PAGE_SIZE = 10
MAX_TITLE = 60
MAX_BODY = 3000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CAPTION = 1024
FILE_FOLDERS = {"document": ("pdf", "pdf"), "photo": ("images", "jpg")}
TO_MAIN_MENU = InlineKeyboardButton("❌ Cancel", callback_data="troubleshooter:home")
TO_LIST = InlineKeyboardButton(
    "🔙 Suggestions", callback_data="troubleshooter:suggestions"
)


def menu_paths(tree=None, path=()):
    tree = SETTINGS.content.MODULES_MAP if tree is None else tree
    paths = [path] if not path else []
    for title, data in tree.items():
        if isinstance(data, dict) and "menu" in data:
            paths.append((*path, title))
            paths += menu_paths(data["menu"], (*path, title))
    return paths


def menu_at(location):
    node = SETTINGS.content.MODULES_MAP
    for title in location:
        data = node.get(title)
        if not (isinstance(data, dict) and "menu" in data):
            return None
        node = data["menu"]
    return node


def slug(title):
    return re.sub(r"\W+", "_", title.lower()).strip("_")


def title_problem(location, title, pending=None):
    if not title or len(title) > MAX_TITLE:
        return f"Keep the title between 1 and {MAX_TITLE} characters."
    if not slug(title):
        return "The title needs at least one letter or number."
    node = menu_at(location)
    if node is None:
        return "That menu no longer exists."
    taken = list(node)
    if not location:
        taken += [
            item["title"]
            for item in get_troubleshooter_content().values()
            if not item.get("parent")
        ]
    if any(slug(t) == slug(title) for t in taken):
        return "Something with that title is already in that menu."
    for s in (pending or {}).values():
        if list(s["location"]) == list(location) and slug(s["title"]) == slug(title):
            return (
                "Someone has already suggested that title for this menu, "
                "and it's waiting for approval."
            )
    return None


def where(location):
    return " › ".join(location) if location else "Main menu"


def shown_name(user):
    return f"@{user.username}" if user.username else user.full_name


def file_bot(context):
    if (
        context.bot_data.get("is_troubleshooter")
        or turbine_troubleshooter.application is None
    ):
        return context.bot
    return turbine_troubleshooter.application.bot


async def send_file(bot, chat_id, s, caption=None):
    send = bot.send_photo if s["file_kind"] == "photo" else bot.send_document
    await send(chat_id, s["file_id"], caption=caption, parse_mode="HTML")


async def edit(query, text, kb):
    try:
        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def edit_prompt(update, context, text, kb):
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get("last_msg_id"),
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "troubleshooter:suggest":
        await button_start(query, context)
    elif data.startswith("troubleshooter:suggest:where:"):
        await button_where(query, context)
    elif data == "troubleshooter:suggest:send":
        await button_send(update, context)
    elif data in ("troubleshooter:suggest:attach", "troubleshooter:suggest:text"):
        await button_add(query, context)
    elif not is_owner(query.from_user.id):
        await query.answer("⚠️ Only the owner can do that.", show_alert=True)
    elif data.startswith("troubleshooter:suggestions"):
        page = data.split(":")[2] if data.count(":") == 2 else "0"
        await show_list(query, context, page=int(page) if page.isdigit() else 0)
    elif data.startswith("troubleshooter:suggestion_file:"):
        await button_open_file(query, context)
    elif data.startswith("troubleshooter:suggestion_ok:"):
        await button_approve(query, context)
    elif data.startswith("troubleshooter:suggestion_no:"):
        await button_reject(query, context)
    elif data.startswith("troubleshooter:suggestion:"):
        await show_card(query, context, int(data.split(":")[2]))


async def button_start(query, context):
    paths = menu_paths()
    context.user_data["state"] = None
    context.user_data["suggest"] = {"menus": paths}
    kb = [
        [
            InlineKeyboardButton(
                f"📁 {where(p)}", callback_data=f"troubleshooter:suggest:where:{i}"
            )
        ]
        for i, p in enumerate(paths)
    ]
    kb.append([TO_MAIN_MENU])
    await edit(
        query,
        "📝 <b>Suggest Content</b>\n\n"
        "Suggest a note, document or photo for the bot. The owner checks it "
        "before anyone else sees it.\n\nWhere should it go?",
        kb,
    )


async def button_where(query, context):
    draft = context.user_data.get("suggest") or {}
    menus = draft.get("menus", [])
    i = int(query.data.split(":")[3])
    if i >= len(menus):
        await button_start(query, context)
        return
    draft["location"] = list(menus[i])
    context.user_data["suggest"] = draft
    context.user_data["state"] = "troubleshooter:suggest:title"
    context.user_data["last_msg_id"] = query.message.message_id
    await edit(
        query,
        f"📝 <b>Suggest Content</b> · {html.escape(where(menus[i]))}\n\n"
        "Type a short title for the new item:",
        [[TO_MAIN_MENU]],
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    state = context.user_data.get("state")
    draft = context.user_data.get("suggest") or {}
    if "location" not in draft:
        context.user_data["state"] = None
        return

    if state == "troubleshooter:suggest:title":
        problem = title_problem(
            draft["location"], text, context.bot_data.get("pending_suggestions")
        )
        if problem:
            await edit_prompt(
                update,
                context,
                f"📝 <b>Suggest Content</b>\n\n⚠️ {problem}\n\nType a short title:",
                [[TO_MAIN_MENU]],
            )
            return
        draft["title"] = text
        context.user_data["state"] = "troubleshooter:suggest:body"
        ask = "Now send the text for it"
        if files_allowed(context):
            ask += ", or a PDF or photo (you can add text with it)"
        await edit_prompt(
            update,
            context,
            f"📝 <b>{html.escape(text)}</b>\n\n{ask}:",
            [[TO_MAIN_MENU]],
        )
        return

    if state == "troubleshooter:suggest:body":
        draft.update(body=text[:MAX_BODY], file_id=None, file_kind=None)
        await show_confirm(update, context, draft)
    elif state == "troubleshooter:suggest:text":
        draft["body"] = text[:MAX_BODY]
        await show_confirm(update, context, draft)


def files_allowed(context):
    return bool(context.bot_data.get("is_troubleshooter") and SETTINGS.files_dir)


async def button_add(query, context):
    draft = context.user_data.get("suggest") or {}
    if "title" not in draft:
        await edit(
            query,
            "⚠️ That suggestion has expired. Please start again.",
            [[TO_MAIN_MENU]],
        )
        return
    attach = query.data.endswith(":attach")
    context.user_data["state"] = (
        "troubleshooter:suggest:file" if attach else "troubleshooter:suggest:text"
    )
    context.user_data["last_msg_id"] = query.message.message_id
    await edit(
        query,
        f"📝 <b>{html.escape(draft['title'])}</b>\n\n"
        + ("Send the PDF or photo:" if attach else "Type the text for it:"),
        [[TO_MAIN_MENU]],
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get("suggest") or {}
    message = update.message
    if context.user_data.get("state") not in (
        "troubleshooter:suggest:body",
        "troubleshooter:suggest:file",
    ):
        return
    try:
        await message.delete()
    except Exception:
        pass

    problem = None
    if not SETTINGS.files_dir:
        problem = "This bot can't take files. Send the text instead."
    elif message.photo:
        file, kind = message.photo[-1], "photo"
    elif message.document and message.document.mime_type == "application/pdf":
        file, kind = message.document, "document"
    else:
        problem = "Only PDFs and photos can be suggested."
    if not problem and (file.file_size or 0) > MAX_FILE_BYTES:
        problem = "That file is over 20 MB, which is too big for the bot to handle."
    if problem:
        await edit_prompt(
            update,
            context,
            f"📝 <b>{html.escape(draft.get('title', ''))}</b>\n\n⚠️ {problem}",
            [[TO_MAIN_MENU]],
        )
        return

    draft.update(file_id=file.file_id, file_kind=kind)
    if message.caption or "body" not in draft:
        draft["body"] = (message.caption or "")[:MAX_BODY]
    await show_confirm(update, context, draft)


async def show_confirm(update, context, draft):
    context.user_data["state"] = None
    attached = {"photo": "\n📎 Photo attached", "document": "\n📎 PDF attached"}
    text = (
        "📝 <b>Check your suggestion</b>\n\n"
        f"Where: {html.escape(where(draft['location']))}\n"
        f"Title: {html.escape(draft['title'])}"
        f"{attached.get(draft['file_kind'], '')}\n\n"
        f"{html.escape(draft['body'])}"
    )
    caption = f"*{draft['title']}*\n\n{escape_markdown(draft['body'])}"
    over = len(caption) - MAX_CAPTION if draft["file_kind"] else 0
    kb = []
    if over > 0:
        text += (
            f"\n\n⚠️ Text sent with a file has to be shorter. "
            f"Cut {over} characters, or remove the file by starting again."
        )
    else:
        kb.append(
            [
                InlineKeyboardButton(
                    "✅ Send for approval", callback_data="troubleshooter:suggest:send"
                )
            ]
        )
    if not draft["file_kind"] and files_allowed(context):
        kb.append(
            [
                InlineKeyboardButton(
                    "📎 Attach a PDF or photo",
                    callback_data="troubleshooter:suggest:attach",
                )
            ]
        )
    kb.append(
        [
            InlineKeyboardButton(
                "✏️ Change text" if draft["body"] else "✏️ Add text",
                callback_data="troubleshooter:suggest:text",
            )
        ]
    )
    kb.append([TO_MAIN_MENU])
    await edit_prompt(update, context, text, kb)


async def button_send(update, context):
    query = update.callback_query
    draft = context.user_data.pop("suggest", None) or {}
    back = [[InlineKeyboardButton("🔙 Main Menu", callback_data="troubleshooter:home")]]
    if "body" not in draft:
        await edit(query, "⚠️ That suggestion has expired. Please start again.", back)
        return
    problem = title_problem(
        draft["location"], draft["title"], context.bot_data.get("pending_suggestions")
    )
    if problem:
        await edit(query, f"⚠️ {problem}\n\nPlease start again.", back)
        return

    user = query.from_user
    s = {
        "user_id": user.id,
        "name": shown_name(user),
        "location": draft["location"],
        "title": draft["title"],
        "body": draft["body"],
        "file_id": draft.get("file_id"),
        "file_kind": draft.get("file_kind"),
    }
    s["id"] = await suggestion_add(s)
    context.bot_data.setdefault("pending_suggestions", {})[s["id"]] = s

    await context.bot.send_message(
        SETTINGS.alerts_chat_id,
        f"📝 *Content Suggestion*\n\nFrom: {escape_markdown(s['name'])}\n"
        f"Where: {escape_markdown(where(s['location']))}\n"
        f"Title: {escape_markdown(s['title'])}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📝 Review",
                        callback_data=f"troubleshooter:suggestion:{s['id']}",
                    )
                ]
            ]
        ),
    )
    await edit(
        query,
        "✅ <b>Sent for approval.</b>\n\nYou'll get a message when it's been checked.",
        back,
    )


async def show_list(query, context, status=None, page=0):
    pending = list(context.bot_data.get("pending_suggestions", {}).values())
    pages = max((len(pending) - 1) // PAGE_SIZE + 1, 1)
    page = min(max(page, 0), pages - 1)
    text = f"{status}\n\n" if status else ""
    text += f"📝 <b>Suggestions</b> ({len(pending)})\n\n"
    text += "Tap one to review it." if pending else "Nothing waiting."
    if pages > 1:
        text += f"\n\nPage {page + 1} of {pages}"

    kb = [
        [
            InlineKeyboardButton(
                f"{'📎' if s['file_id'] else '📝'} {s['title']}",
                callback_data=f"troubleshooter:suggestion:{s['id']}",
            )
        ]
        for s in pending[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "◀️ Prev", callback_data=f"troubleshooter:suggestions:{page - 1}"
            )
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                "Next ▶️", callback_data=f"troubleshooter:suggestions:{page + 1}"
            )
        )
    if nav:
        kb.append(nav)
    kb.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
    )
    await edit(query, text, kb)


async def show_card(query, context, suggestion_id, status=None):
    s = context.bot_data.get("pending_suggestions", {}).get(suggestion_id)
    if s is None:
        await show_list(query, context, status="ℹ️ That suggestion has been dealt with.")
        return
    body = s["body"] or "<i>(no text)</i>"
    if s["body"]:
        body = html.escape(s["body"][:1000]) + ("…" if len(s["body"]) > 1000 else "")
    text = (f"{status}\n\n" if status else "") + (
        f"📝 <b>{html.escape(s['title'])}</b>\n\n"
        f"From: {html.escape(str(s['name']))}\n"
        f"Where: {html.escape(where(s['location']))}\n"
        + (
            f"📎 {'Photo' if s['file_kind'] == 'photo' else 'PDF'} attached\n"
            if s["file_id"]
            else ""
        )
        + f"\n{body}"
    )
    kb = []
    if s["file_id"]:
        kb.append(
            [
                InlineKeyboardButton(
                    "📎 Open file",
                    callback_data=f"troubleshooter:suggestion_file:{suggestion_id}",
                )
            ]
        )
    kb.append(
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"troubleshooter:suggestion_ok:{suggestion_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"troubleshooter:suggestion_no:{suggestion_id}",
            ),
        ]
    )
    kb.append([TO_LIST])
    await edit(query, text, kb)


def suggestion_of(query, context):
    suggestion_id = int(query.data.split(":")[2])
    return suggestion_id, context.bot_data.get("pending_suggestions", {}).get(
        suggestion_id
    )


async def button_open_file(query, context):
    suggestion_id, s = suggestion_of(query, context)
    if not s or not s["file_id"]:
        await show_card(query, context, suggestion_id)
        return
    bot = file_bot(context)
    chat_id = query.message.chat_id if bot is context.bot else SETTINGS.owner_id
    await send_file(bot, chat_id, s, caption=html.escape(s["title"]))
    await query.answer("📎 Sent above." if bot is context.bot else "📎 Sent to you.")


async def finish(context, s, message):
    context.bot_data.get("pending_suggestions", {}).pop(s["id"], None)
    await suggestion_remove(s["id"])
    try:
        await context.bot.send_message(s["user_id"], message)
    except Exception:
        pass


def file_path(s):
    folder, ext = FILE_FOLDERS[s["file_kind"]]
    name = re.sub(r"[^\w\- ]+", "", s["title"]).strip() or f"suggestion {s['id']}"
    rel = f"{folder}/{name}.{ext}"
    if (Path(SETTINGS.files_dir) / rel).exists():
        rel = f"{folder}/{name} ({s['id']}).{ext}"
    return rel


async def button_approve(query, context):
    suggestion_id, s = suggestion_of(query, context)
    if s is None:
        await show_card(query, context, suggestion_id)
        return
    problem = title_problem(s["location"], s["title"])
    if problem:
        await show_card(query, context, suggestion_id, status=f"⚠️ {problem}")
        return

    body = escape_markdown(s["body"] or "")
    rel = None
    if s["file_id"]:
        rel = file_path(s)
        entry = {"text": body, s["file_kind"]: Path(SETTINGS.files_dir) / rel}
    else:
        entry = body
    node = menu_at(s["location"])
    node[s["title"]] = entry
    try:
        await content_save()
    except Exception:
        node.pop(s["title"], None)
        raise

    done = f"✅ Your suggestion “{s['title']}” has been added to the bot."
    if rel:
        done += " Its file will work once the owner uploads it."
    await finish(context, s, done)

    status = (
        f"✅ Added “{html.escape(s['title'])}” to {html.escape(where(s['location']))}."
    )
    if rel:
        bot = file_bot(context)
        chat_id = query.message.chat_id if bot is context.bot else SETTINGS.owner_id
        await send_file(
            bot,
            chat_id,
            s,
            caption=f"📎 Save this as <code>{html.escape(rel)}</code> in the files "
            "folder and deploy. Until then the menu item says it isn't available.",
        )
        status += "\n📎 The file has been sent to you to upload."
    await show_list(query, context, status=status)


async def button_reject(query, context):
    suggestion_id, s = suggestion_of(query, context)
    if s is None:
        await show_card(query, context, suggestion_id)
        return
    await finish(context, s, f"❌ Your suggestion “{s['title']}” wasn't added.")
    await show_list(query, context, status=f"❌ Rejected “{html.escape(s['title'])}”.")
