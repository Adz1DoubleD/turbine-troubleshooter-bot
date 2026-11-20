import html
from types import SimpleNamespace

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    attachments_remove,
    delete_entry,
    delete_request_add,
    delete_request_remove,
    fault_code_add,
    menu_node_delete,
    menu_node_update,
    part_update,
)
from turbine_troubleshooter.helpers import escape_markdown, is_owner, own_bot
from turbine_troubleshooter.settings import SETTINGS

from ...notify import send_notification_troubleshooter
from . import local_now
from .users import (
    OWNER_ONLY,
    PAGE_SIZE,
    edit,
    nav_row,
    page_count,
    pending_requests,
    tell_user,
)

KINDS = {"code": "code", "part": "part", "menu": "menu item"}


async def ask_owner_to_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, kind, target, label
):
    user = update.effective_user
    name = f"@{user.username}" if user.username else user.full_name
    request_id = await delete_request_add(kind, target, label, user.id, name)
    if not request_id:
        return "⏳ The owner has already been asked to delete that."

    context.bot_data.setdefault("pending_delete_requests", {})[request_id] = {
        "id": request_id,
        "kind": kind,
        "target": str(target),
        "label": label,
        "user_id": user.id,
        "name": name,
    }
    try:
        await own_bot(context).send_message(
            SETTINGS.alerts_chat_id,
            f"🗑 *Delete request*\n\n{escape_markdown(name)} wants to delete the "
            f"{KINDS[kind]}: {escape_markdown(label)}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Delete",
                            callback_data=f"troubleshooter:delreq:yes:{request_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ Keep",
                            callback_data=f"troubleshooter:delreq:no:{request_id}",
                        ),
                    ]
                ]
            ),
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)
    return "🗑 Sent to the owner to approve. It stays until they do."


async def button_delete_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Only the owner can do that.", show_alert=True)
        return

    pending = context.bot_data.setdefault("pending_delete_requests", {})
    status = ""
    bits = query.data.split(":")
    if len(bits) >= 4:
        request = pending.pop(int(bits[3]), None)
        if request is None:
            status = "ℹ️ That request has already been dealt with."
        else:
            await delete_request_remove(request["id"])
            kind = KINDS[request["kind"]]
            label = request["label"]
            if bits[2] == "yes":
                requester = SimpleNamespace(
                    id=request["user_id"], username=None, full_name=request["name"]
                )
                done = False
                if request["kind"] == "code":
                    done = await delete_entry("codes", "code", request["target"])
                    context.bot_data.get("codes", {}).pop(request["target"], None)
                    if done:
                        await send_notification_troubleshooter(
                            requester, "code_deleted", request["target"]
                        )
                elif request["kind"] == "part":
                    parts = context.bot_data.get("parts", [])
                    part = next(
                        (p for p in parts if str(p.get("id")) == request["target"]),
                        None,
                    )
                    done = await delete_entry("parts", "id", int(request["target"]))
                    if part:
                        parts.remove(part)
                    if done and part:
                        await send_notification_troubleshooter(
                            requester,
                            "part_deleted",
                            part["part_no"],
                            part["description"],
                        )
                elif request["kind"] == "menu" and SETTINGS.menu is not None:
                    nodes = SETTINGS.menu["nodes"]
                    node = next(
                        (n for n in nodes if str(n["id"]) == request["target"]), None
                    )
                    if node and not any(n["parent_id"] == node["id"] for n in nodes):
                        done = await menu_node_delete(node["id"])
                        nodes.remove(node)
                        SETTINGS.menu["attachments"][:] = [
                            a
                            for a in SETTINGS.menu["attachments"]
                            if a["node_id"] != node["id"]
                        ]
                        await send_notification_troubleshooter(
                            requester, "menu_deleted", label
                        )
                    elif node:
                        label += " (it has items in it now, so it was kept)"
                status = (
                    f"✅ Deleted the {kind}: {label}"
                    if done
                    else f"ℹ️ Not deleted: {label}"
                )
                told = (
                    f"✅ The owner deleted the {kind} you asked about: {label}"
                    if done
                    else f"ℹ️ The {kind} you asked to delete wasn't deleted: {label}"
                )
            else:
                status = f"❌ Kept the {kind}: {label}"
                told = f"❌ The owner kept the {kind} you asked to delete: {label}"
            await tell_user(context, request["user_id"], told)

    if len(bits) == 3 or query.data.endswith(":p"):
        await show_pending(query, context, status=html.escape(status) or None)
        return
    await query.edit_message_text(
        status,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Close", callback_data="cancel")]]
        ),
    )


async def button_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Only the owner can do that.", show_alert=True)
        return

    _, _, kind, item_id, index = query.data.split(":")
    if kind == "file":
        attachments = (SETTINGS.menu or {}).get("attachments", [])
        added = next((a for a in attachments if str(a.get("id")) == item_id), None)
        if not added or any(
            a["node_id"] == added["node_id"] and a is not added for a in attachments
        ):
            await query.answer(
                "⚠️ That file has been removed or replaced since, so this can't "
                "be undone.",
                show_alert=True,
            )
            return
        await attachments_remove(added["node_id"])
        attachments[:] = [a for a in attachments if a is not added]
        page = next(
            (n for n in SETTINGS.menu["nodes"] if n["id"] == added["node_id"]), {}
        )
        await send_notification_troubleshooter(
            query.from_user,
            "menu_edited",
            page.get("title", ""),
            message="File removed (undone)",
        )
        await query.answer("↩️ Undone. The file is off the page.", show_alert=True)
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Close", callback_data="cancel")]]
            )
        )
        return
    if kind == "menu":
        item = next(
            (
                n
                for n in (SETTINGS.menu or {}).get("nodes", [])
                if str(n["id"]) == item_id
            ),
            None,
        )
    elif kind == "code":
        item = next(
            (
                c
                for c in context.bot_data.get("codes", {}).values()
                if str(c.get("id")) == item_id
            ),
            None,
        )
    else:
        item = next(
            (
                p
                for p in context.bot_data.get("parts", [])
                if str(p.get("id")) == item_id
            ),
            None,
        )
    edits = (item or {}).get("edits") or []
    changes = edits[int(index)].get("changes") if int(index) < len(edits) else None

    if not changes:
        await query.answer("⚠️ That edit can't be undone any more.", show_alert=True)
        return
    if any((item.get(f) or "") != (new or "") for f, (_, new) in changes.items()):
        await query.answer(
            "⚠️ It's been changed again since, so this edit can't be undone.",
            show_alert=True,
        )
        return

    user = query.from_user
    editor = f"@{user.username}" if user.username else user.full_name
    edited_at = local_now().strftime("%Y-%m-%d %H:%M")
    back = {f: [new, old] for f, (old, new) in changes.items()}

    if kind == "menu":
        for field, (old, new) in changes.items():
            await menu_node_update(
                item["id"], field, old, user.id, editor, edited_at, new
            )
            item[field] = old
        await send_notification_troubleshooter(
            user, "menu_edited", item["title"], message="Undone"
        )
    elif kind == "code":
        restored = {**item, **{f: old for f, (old, _) in changes.items()}}
        await fault_code_add(
            code=item["code"],
            advice=restored.get("advice"),
            parts=restored.get("parts"),
            edited_by=editor,
            edited_at=edited_at,
            changes=back,
        )
        item.update(advice=restored.get("advice"), parts=restored.get("parts"))
        await send_notification_troubleshooter(
            user, "code_edited", item["code"], item.get("advice"), item.get("parts")
        )
    else:
        for field, (old, new) in changes.items():
            await part_update(int(item_id), field, old, editor, edited_at, old=new)
            item[field] = old
        await send_notification_troubleshooter(
            user,
            "part_edited",
            item["part_no"],
            item["description"],
            message="; ".join(
                f"{f}: {new or 'None'} → {old or 'None'}"
                for f, (old, new) in changes.items()
            ),
        )

    item["edits"] = edits + [{"by": editor, "at": edited_at, "changes": back}]
    await query.answer("↩️ Undone.", show_alert=True)
    await query.edit_message_reply_markup(
        InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Close", callback_data="cancel")]]
        )
    )


async def show_pending(query, context, status=None, page=None):
    requests = pending_requests(context) + [
        (r["id"], r, "delete")
        for r in context.bot_data.get("pending_delete_requests", {}).values()
    ]
    pages = page_count(len(requests))
    if page is None:
        page = context.user_data.get("pending_page", 0)
    page = min(max(page, 0), pages - 1)
    context.user_data["pending_page"] = page
    shown = requests[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    text = f"{status}\n\n" if status else ""
    text += f"📥 <b>Requests</b> ({len(requests)})\n\n"
    if not requests:
        text += "Nothing waiting."
    else:
        text += "\n".join(
            f"• {html.escape(str(r['name'] or r['user_id']))} wants to delete the "
            f"{KINDS[r['kind']]}: {html.escape(r['label'])}"
            if kind == "delete"
            else f"• {html.escape(str(r))} wants "
            f"{'admin' if kind == 'admin' else 'access'}"
            for _, r, kind in shown
        )
        if pages > 1:
            text += f"\n\nPage {page + 1} of {pages}"

    kb = [
        [
            InlineKeyboardButton(
                f"✅ Delete {r['label'][:30]}",
                callback_data=f"troubleshooter:delreq:yes:{uid}:p",
            ),
            InlineKeyboardButton(
                "❌ Keep", callback_data=f"troubleshooter:delreq:no:{uid}:p"
            ),
        ]
        if kind == "delete"
        else [
            InlineKeyboardButton(
                f"✅ {r}{' (admin)' if kind == 'admin' else ''}",
                callback_data=f"troubleshooter:{kind}:approve:{uid}:p",
            ),
            InlineKeyboardButton(
                "❌ Deny", callback_data=f"troubleshooter:{kind}:deny:{uid}:p"
            ),
        ]
        for uid, r, kind in shown
    ]
    kb += nav_row("troubleshooter:pending:", page, pages)
    kb.append(
        [
            InlineKeyboardButton(
                "🔙 Admin Panel", callback_data="troubleshooter:admin_menu"
            )
        ]
    )
    await edit(query, text, kb)


async def button_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer(OWNER_ONLY, show_alert=True)
        return
    parts = query.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await show_pending(query, context, page=page)
