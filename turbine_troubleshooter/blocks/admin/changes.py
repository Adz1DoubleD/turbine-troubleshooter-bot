from types import SimpleNamespace

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    delete_entry,
    delete_request_add,
    delete_request_remove,
    fault_code_add,
    part_update,
)
from turbine_troubleshooter.helpers import escape_markdown, is_owner, own_bot
from turbine_troubleshooter.settings import SETTINGS

from ...tools import send_notification_troubleshooter
from . import local_now
from .users import tell_user

KINDS = {"code": "code", "part": "part", "menu": "menu item"}


async def ask_owner_to_delete(update, context, kind, target, label):
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
            SETTINGS.owner_id,
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
    if len(bits) == 4:
        request = pending.pop(int(bits[3]), None)
        if request is None:
            status = "ℹ️ That request has already been dealt with.\n\n"
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
                status = (
                    f"✅ Deleted the {kind}: {escape_markdown(label)}\n\n"
                    if done
                    else f"ℹ️ The {kind} {escape_markdown(label)} was already gone.\n\n"
                )
                told = f"✅ The owner deleted the {kind} you asked about: {label}"
            else:
                status = f"❌ Kept the {kind}: {escape_markdown(label)}\n\n"
                told = f"❌ The owner kept the {kind} you asked to delete: {label}"
            await tell_user(context, request["user_id"], told)

    kb = [
        [
            InlineKeyboardButton(
                f"✅ Delete {r['label'][:30]}",
                callback_data=f"troubleshooter:delreq:yes:{r['id']}",
            ),
            InlineKeyboardButton(
                "❌ Keep", callback_data=f"troubleshooter:delreq:no:{r['id']}"
            ),
        ]
        for r in list(pending.values())[:20]
    ]
    kb.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
    )
    lines = "\n".join(
        f"• {KINDS[r['kind']]}: {escape_markdown(r['label'])} "
        f"({escape_markdown(r['name'] or r['user_id'])})"
        for r in pending.values()
    )
    await query.edit_message_text(
        f"{status}🗑 *Delete requests*\n\n{lines or 'Nothing waiting.'}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def button_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Only the owner can do that.", show_alert=True)
        return

    _, _, kind, item_id, index = query.data.split(":")
    if kind == "code":
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

    if kind == "code":
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
