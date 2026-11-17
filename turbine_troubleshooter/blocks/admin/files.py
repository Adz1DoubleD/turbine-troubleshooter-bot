import base64
import re
from pathlib import Path

import httpx
import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    attachment_add,
    attachment_status,
    attachments_remove,
)
from turbine_troubleshooter.helpers import escape_markdown, is_owner, own_bot
from turbine_troubleshooter.settings import SETTINGS

from ...tools import send_notification_troubleshooter
from .content import EXPIRED, TO_PANEL, handle_text, where

MAX_FILE_BYTES = 20 * 1024 * 1024
FOLDERS = {"document": ("pdf", "pdf"), "photo": ("images", "jpg")}


async def send_to_owner(context, attachment):
    send = (
        own_bot(context).send_photo
        if attachment["type"] == "photo"
        else own_bot(context).send_document
    )
    try:
        await send(
            SETTINGS.owner_id,
            attachment["file_id"],
            caption=f"📎 *File to save*\n\nFor: "
            f"{escape_markdown(where(attachment['node_id']))}\n"
            f"Save it in the files folder as:\n`{attachment['path']}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💾 Save to Repo"
                            if SETTINGS.files_repo and SETTINGS.files_repo_token
                            else "💾 Save to Files Folder",
                            callback_data="troubleshooter:menu_files:save:"
                            f"{attachment['id']}",
                        )
                    ]
                ]
            )
            if (SETTINGS.files_repo and SETTINGS.files_repo_token) or SETTINGS.files_dir
            else None,
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)


async def attach(context, user, node, file):
    folder, ext = FOLDERS[file["type"]]
    base = re.sub(r"\W+", "_", node["title"].lower()).strip("_") or "file"
    taken = {a["path"] for a in SETTINGS.menu["attachments"]}
    path, n = f"{folder}/{base}.{ext}", 2
    while path in taken or (Path(SETTINGS.files_dir) / path).exists():
        path, n = f"{folder}/{base}_{n}.{ext}", n + 1
    attachment = await attachment_add(
        node["id"], file["type"], file["file_id"], file["file_unique_id"], path, user.id
    )
    SETTINGS.menu["attachments"].append(attachment)
    await send_to_owner(context, attachment)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    bits = query.data.split(":")
    action = bits[1]
    draft = context.user_data.get("menu_draft") or {}
    node_id = int(bits[-1]) if bits[-1].isdigit() else draft.get("node")
    node = next((n for n in SETTINGS.menu["nodes"] if n["id"] == node_id), None)
    text, kb = EXPIRED, [[TO_PANEL]]

    if action == "menu_edit" and bits[2] == "file" and node:
        attached = any(a["node_id"] == node["id"] for a in SETTINGS.menu["attachments"])
        if attached and not is_owner(user.id):
            await query.answer(
                "⚠️ Only the owner can replace or remove a file.", show_alert=True
            )
            return
        context.user_data["menu_draft"] = {"node": node["id"], "field": "file"}
        context.user_data["state"] = "troubleshooter:menu_edit:file"
        text = (
            f"📎 *File* · {escape_markdown(where(node['id']))}\n\n"
            "Send the PDF or photo"
            + (" to replace the one there now." if attached else ".")
        )
        kb = (
            [
                [
                    InlineKeyboardButton(
                        "🗑 Remove File",
                        callback_data=f"troubleshooter:menu_file_rm:{node['id']}",
                    )
                ]
            ]
            if attached
            else []
        ) + [
            [
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"troubleshooter:menu:{node['id']}"
                )
            ]
        ]

    elif (
        query.data == "troubleshooter:menu_edit:save"
        and node
        and draft.get("field") == "file"
        and draft.get("file")
    ):
        replaced = await attachments_remove(node["id"]) if is_owner(user.id) else 0
        SETTINGS.menu["attachments"][:] = [
            a
            for a in SETTINGS.menu["attachments"]
            if not replaced or a["node_id"] != node["id"]
        ]
        await attach(context, user, node, draft["file"])
        context.user_data.pop("menu_draft", None)
        await send_notification_troubleshooter(
            user,
            "menu_edited",
            where(node["id"]),
            message="File replaced" if replaced else "File added",
        )
        text = f"✅ *Saved* · {escape_markdown(where(node['id']))}"
        kb = [
            [
                InlineKeyboardButton(
                    "👀 Open It", callback_data=f"troubleshooter:menu:{node['id']}"
                )
            ],
            [TO_PANEL],
        ]

    elif action == "menu_file_rm" and node and is_owner(user.id):
        if len(bits) == 3:
            text = (
                f"⚠️ *Remove the file?*\n\n{escape_markdown(where(node['id']))} "
                "keeps its text."
            )
            kb = [
                [
                    InlineKeyboardButton(
                        "❌ No, Cancel",
                        callback_data=f"troubleshooter:menu:{node['id']}",
                    ),
                    InlineKeyboardButton(
                        "✅ Yes, Remove",
                        callback_data=f"troubleshooter:menu_file_rm:yes:{node['id']}",
                    ),
                ]
            ]
        else:
            await attachments_remove(node["id"])
            SETTINGS.menu["attachments"][:] = [
                a for a in SETTINGS.menu["attachments"] if a["node_id"] != node["id"]
            ]
            context.user_data["state"] = None
            await send_notification_troubleshooter(
                user, "menu_edited", where(node["id"]), message="File removed"
            )
            text = f"✅ *File removed* · {escape_markdown(where(node['id']))}"
            kb = [
                [
                    InlineKeyboardButton(
                        "👀 Open It", callback_data=f"troubleshooter:menu:{node['id']}"
                    )
                ],
                [TO_PANEL],
            ]

    elif action == "menu_files" and is_owner(user.id):
        pending = [
            a
            for a in SETTINGS.menu["attachments"]
            if a["status"] in ("pending", "committed")
        ]
        repo = SETTINGS.files_repo and SETTINGS.files_repo_token
        chosen = next(
            (
                a
                for a in pending
                if len(bits) == 4
                and a["id"] == int(bits[3])
                and a["status"] == "pending"
            ),
            None,
        )
        if len(bits) == 4 and bits[2] == "send":
            if chosen:
                await send_to_owner(context, chosen)
            await query.answer("📤 Sent." if chosen else "Already saved.")
            return
        if len(bits) == 4 and bits[2] == "save":
            if not chosen or not (repo or SETTINGS.files_dir):
                await query.answer("Already saved.")
                return
            if not repo:
                await query.answer("💾 Saving…")
                target = Path(SETTINGS.files_dir) / chosen["path"]
                try:
                    data = await (
                        await own_bot(context).get_file(chosen["file_id"])
                    ).download_as_bytearray()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bytes(data))
                    await attachment_status(chosen["id"], "saved")
                    chosen["status"] = "saved"
                    reply = f"💾 Saved {chosen['path']} in the files folder."
                except Exception as e:
                    sentry_sdk.capture_exception(e)
                    reply = (
                        f"⚠️ Couldn't save {chosen['path']} in the files folder. "
                        "Try again later."
                    )
                await own_bot(context).send_message(SETTINGS.owner_id, reply)
                return
            await query.answer("💾 Saving to the repo…")
            try:
                folder = (
                    Path(SETTINGS.files_dir)
                    .resolve()
                    .relative_to(Path.cwd().resolve())
                    .as_posix()
                )
            except (TypeError, ValueError):
                await own_bot(context).send_message(
                    SETTINGS.owner_id,
                    f"⚠️ Couldn't save {chosen['path']} to the repo. The files folder "
                    "isn't inside the folder the bot runs from, so its place in the "
                    "repo can't be worked out.",
                )
                return
            status = None
            try:
                data = await (
                    await own_bot(context).get_file(chosen["file_id"])
                ).download_as_bytearray()
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.put(
                        f"https://api.github.com/repos/{SETTINGS.files_repo}/contents/"
                        + "/".join(
                            p for p in (folder, chosen["path"]) if p not in ("", ".")
                        ),
                        headers={
                            "Authorization": f"Bearer {SETTINGS.files_repo_token}",
                            "Accept": "application/vnd.github+json",
                        },
                        json={
                            "message": f"Add {chosen['path']} from the troubleshooter bot",
                            "content": base64.b64encode(bytes(data)).decode(),
                            "branch": SETTINGS.files_repo_branch or "main",
                        },
                    )
                status = response.status_code
            except Exception as e:
                sentry_sdk.capture_exception(e)
            if status in (200, 201):
                await attachment_status(chosen["id"], "committed")
                chosen["status"] = "committed"
                reply = (
                    f"💾 Saved {chosen['path']} to the repo. It's in the files folder "
                    "after the next deploy."
                )
            else:
                if status:
                    sentry_sdk.capture_message(
                        f"Troubleshooter file save to repo failed: HTTP {status}",
                        level="warning",
                    )
                reply = f"⚠️ Couldn't save {chosen['path']} to the repo. " + {
                    401: "The token isn't valid.",
                    403: "The token can't write to that repo.",
                    404: "The repo, folder or branch wasn't found.",
                    409: "The branch changed while saving. Try again.",
                    422: "A file with that name is already there.",
                }.get(status, "Try again later.")
            await own_bot(context).send_message(SETTINGS.owner_id, reply)
            return
        text = (
            f"📎 *Pending Files* ({len(pending)})\n\n"
            "These were added in the bot but aren't in the files folder yet. "
            + (
                "Tap 💾 to save one to the repo, or save it yourself as shown. "
                "The bot marks it saved when it next starts."
                if repo
                else "Tap 💾 to save one in the files folder, or save it yourself "
                "as shown."
            )
            + "\n\n"
            + (
                "\n".join(
                    f"• {escape_markdown(where(a['node_id']))}: `{a['path']}`"
                    + (
                        " (in the repo, live after the next deploy)"
                        if a["status"] == "committed"
                        else ""
                    )
                    for a in pending
                )
                or "Nothing waiting."
            )
        )
        kb = [
            [
                InlineKeyboardButton(
                    f"📤 {where(a['node_id'])[:30]}",
                    callback_data=f"troubleshooter:menu_files:send:{a['id']}",
                )
            ]
            + (
                [
                    InlineKeyboardButton(
                        "💾 Save",
                        callback_data=f"troubleshooter:menu_files:save:{a['id']}",
                    )
                ]
                if repo or SETTINGS.files_dir
                else []
            )
            for a in pending[:20]
            if a["status"] == "pending"
        ] + [[TO_PANEL]]

    markup = InlineKeyboardMarkup(kb)
    if query.message.text:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        context.user_data["last_msg_id"] = query.message.message_id
    else:
        sent = await context.bot.send_message(
            query.message.chat_id, text, parse_mode="Markdown", reply_markup=markup
        )
        context.user_data["last_msg_id"] = sent.message_id


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    state = context.user_data.get("state")
    draft = context.user_data.get("menu_draft") or {}
    if SETTINGS.menu is None or state not in (
        "troubleshooter:menu_add:body",
        "troubleshooter:menu_edit:file",
    ):
        return
    try:
        await message.delete()
    except Exception:
        pass

    node = next(
        (n for n in SETTINGS.menu["nodes"] if n["id"] == draft.get("node")), None
    )
    problem = None
    if message.photo:
        file, kind = message.photo[-1], "photo"
    elif message.document and message.document.mime_type == "application/pdf":
        file, kind = message.document, "document"
    else:
        problem = "Only PDFs and photos can be added."
    if not problem and (file.file_size or 0) > MAX_FILE_BYTES:
        problem = "That file is over 20 MB, which is too big for the bot."
    used = not problem and next(
        (
            a
            for a in SETTINGS.menu["attachments"]
            if a.get("file_unique_id") == file.file_unique_id
        ),
        None,
    )
    if used:
        problem = f"That file is already on {where(used['node_id'])}."
    if problem:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get("last_msg_id"),
            text=f"⚠️ {problem}\n\nSend a PDF or photo:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data=f"troubleshooter:menu:{node['id']}"
                            if node
                            else "troubleshooter:admin_menu",
                        )
                    ]
                ]
            ),
        )
        return

    draft["file"] = {
        "type": kind,
        "file_id": file.file_id,
        "file_unique_id": file.file_unique_id,
    }
    await handle_text(
        update, context, (node["body"] or "") if node else (message.caption or "")
    )
