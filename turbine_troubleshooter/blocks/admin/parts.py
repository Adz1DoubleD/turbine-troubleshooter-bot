"""Adding, editing and deleting spare parts."""

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    delete_entry,
    part_add,
    part_update,
)
from turbine_troubleshooter.helpers import escape_markdown, is_owner

from ...helpers import user_is_admin
from ...notify import send_notification_troubleshooter
from . import handle_block, local_now
from .changes import ask_owner_to_delete

PART_FIELDS = {
    "part_no": ("🔢", "Part Number", 20),
    "description": ("📝", "Description", 160),
    "section": ("📂", "Section", 60),
}


async def button_part_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    await query.answer()

    context.user_data["state"] = "troubleshooter:part_add:part_no"
    context.user_data["last_msg_id"] = query.message.message_id
    await query.edit_message_text(
        "🔩 *Add Spare Part*\n\nStep 1: Enter the *Part Number*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 Back", callback_data="troubleshooter:admin_menu"
                    )
                ]
            ]
        ),
    )


async def button_part_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    part = _find_part(context, int(query.data.split(":")[-1]))
    if not part:
        await query.answer(
            "❌ Part not found — it may have been removed.", show_alert=True
        )
        return

    await query.answer()
    context.user_data["state"] = None
    context.user_data["last_msg_id"] = query.message.message_id
    await _show_part(context, query.message.chat_id, query.message.message_id, part)


async def button_part_edit_field(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    assert context.user_data is not None
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    _, _, field, part_id = query.data.split(":")
    part = _find_part(context, int(part_id))
    if not part or field not in PART_FIELDS:
        await query.answer("❌ Part not found.", show_alert=True)
        return

    await query.answer()
    _, label, limit = PART_FIELDS[field]
    current = escape_markdown(part.get(field) or "") or "_None_"
    clear_hint = "\n_Send_ `-` _to clear it._" if field == "section" else ""

    context.user_data["state"] = f"troubleshooter:part_await_edit:{field}:{part_id}"
    context.user_data["last_msg_id"] = query.message.message_id

    await query.edit_message_text(
        f"✏️ *Updating {label}*\n\n"
        f"*Current:* {current}\n\n"
        f"Enter the new {label.lower()} (max {limit} characters):{clear_hint}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 Cancel", callback_data=f"troubleshooter:part_edit:{part_id}"
                    )
                ]
            ]
        ),
    )


async def handle_part_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: str
) -> None:
    user_data = context.user_data
    parts = context.bot_data.setdefault("parts", [])

    if state == "troubleshooter:part_add:part_no":
        part_no = text.strip().upper()
        existing = [p for p in parts if p["part_no"] == part_no]

        if existing:
            user_data["state"] = None
            lines = "\n".join(
                f"• {escape_markdown(p['description'])}"
                + (f" _({escape_markdown(p['section'])})_" if p.get("section") else "")
                for p in existing
            )
            edit = [
                InlineKeyboardButton(
                    f"✏️ Edit {p['part_no']}",
                    callback_data=f"troubleshooter:part_edit:{p['id']}",
                )
                for p in existing
                if p.get("id")
            ]
            kb = [edit[i : i + 2] for i in range(0, len(edit), 2)]
            kb.append(
                [
                    InlineKeyboardButton(
                        "🔙 Back", callback_data="troubleshooter:admin_menu"
                    )
                ]
            )

            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=user_data.get("last_msg_id"),
                text=f"⚠️ *Part `{part_no}` already exists!*\n\n{lines}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

        user_data["new_part"] = {"part_no": part_no}
        user_data["state"] = "troubleshooter:part_add:description"

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=user_data.get("last_msg_id"),
            text=f"✅ Part: `{part_no}`\n\nStep 2: Enter the *Description*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 Back", callback_data="troubleshooter:admin_menu"
                        )
                    ]
                ]
            ),
        )
        return

    entry = user_data.pop("new_part")
    entry["description"] = text.strip()[:160]
    user_data["state"] = None

    user = update.effective_user
    added_by = f"@{user.username}" if user.username else user.full_name

    new_id = await part_add(entry["part_no"], entry["description"], added_by=added_by)
    if new_id:
        parts.append(
            {"id": new_id, "section": "", "added_by": added_by, "edits": [], **entry}
        )
        status = f"✅ *Part Added*\n\n`{entry['part_no']}` – {escape_markdown(entry['description'])}"
        await send_notification_troubleshooter(
            update.effective_user, "part_added", entry["part_no"], entry["description"]
        )
    else:
        status = f"⚠️ `{entry['part_no']}` already exists."

    await handle_block(update, context, status=status)


async def handle_part_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: str
) -> None:
    user_data = context.user_data
    user_data["state"] = None
    _, _, field, part_id = state.split(":")
    part_id = int(part_id)

    part = _find_part(context, part_id)
    if not part:
        await handle_block(update, context, status="❌ Part not found.")
        return

    value = text.strip()
    if field == "part_no":
        value = value.upper()
    if field == "section" and value == "-":
        value = ""
    value = value[: PART_FIELDS[field][2]]

    parts = context.bot_data.get("parts", [])
    label = PART_FIELDS[field][1]
    old_value = part.get(field) or ""
    user = update.effective_user
    editor = f"@{user.username}" if user.username else user.full_name
    edited_at = local_now().strftime("%Y-%m-%d %H:%M")

    if not value and field != "section":
        status = f"⚠️ {label} can't be empty."
    elif value == old_value:
        status = "ℹ️ No change."
    elif field == "part_no" and any(
        p["part_no"].upper() == value and p.get("id") != part_id for p in parts
    ):
        status = f"⚠️ `{value}` already exists."
    else:
        await part_update(part_id, field, value, editor, edited_at, old=old_value)
        part[field] = value
        part["edits"] = (part.get("edits") or []) + [
            {"by": editor, "at": edited_at, "changes": {field: [old_value, value]}}
        ]
        status = "✅ *Saved*"
        await send_notification_troubleshooter(
            update.effective_user,
            "part_edited",
            part["part_no"],
            part["description"],
            message=f"{label}: {old_value or 'None'} → {value or 'None'}",
            undo=None
            if is_owner(user.id)
            else f"troubleshooter:undo:part:{part_id}:{len(part['edits']) - 1}",
        )

    await _show_part(
        context, update.effective_chat.id, user_data.get("last_msg_id"), part, status
    )


async def button_part_delete_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    part_id = int(query.data.split(":")[-1])
    part = next(
        (p for p in context.bot_data.get("parts", []) if p.get("id") == part_id), None
    )
    if not part:
        await query.answer("Part not found.", show_alert=True)
        return

    section = f"\n_{escape_markdown(part['section'])}_" if part.get("section") else ""
    owner = is_owner(query.from_user.id)
    await query.edit_message_text(
        f"⚠️ *Are you sure?*\n\nDelete `{part['part_no']}` – "
        f"{escape_markdown(part['description'])}{section}"
        + ("" if owner else "\n\nThe owner has to approve it before it's removed."),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ No, Cancel",
                        callback_data=f"troubleshooter:part_edit:{part_id}",
                    ),
                    InlineKeyboardButton(
                        "✅ Yes, Delete" if owner else "✅ Yes, Ask the Owner",
                        callback_data=f"troubleshooter:part_delete:{part_id}",
                    ),
                ]
            ]
        ),
    )


async def button_part_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    part_id = int(query.data.split(":")[-1])
    parts = context.bot_data.get("parts", [])
    part = next((p for p in parts if p.get("id") == part_id), None)

    if not is_owner(query.from_user.id):
        status = (
            await ask_owner_to_delete(
                update,
                context,
                "part",
                part_id,
                f"{part['part_no']} – {part['description']}",
            )
            if part
            else "⚠️ Part not found."
        )
    elif await delete_entry("parts", "id", part_id):
        if part:
            parts.remove(part)
        part_no = part["part_no"] if part else str(part_id)
        status = f"✅ Part `{part_no}` removed."
        await send_notification_troubleshooter(
            query.from_user,
            "part_deleted",
            part_no,
            part["description"] if part else None,
        )
    else:
        status = "⚠️ Part not found in the database."

    await handle_block(update, context, status=status)


def _find_part(
    context: ContextTypes.DEFAULT_TYPE, part_id: int | str
) -> dict[str, Any] | None:
    return next(
        (p for p in context.bot_data.get("parts", []) if p.get("id") == part_id), None
    )


async def _show_part(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    msg_id: int | None,
    part: dict[str, Any],
    status: str | None = None,
) -> None:
    section = escape_markdown(part["section"]) if part.get("section") else "_None_"
    text = (f"{status}\n\n" if status else "") + (
        f"🔩 *Edit Part*\n\n"
        f"*Part Number:* `{part['part_no']}`\n"
        f"*Description:* {escape_markdown(part['description'])}\n"
        f"*Section:* {section}\n\n"
        f"Select a field to change:"
    )
    kb = [
        [
            InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"troubleshooter:part_edit_field:{field}:{part['id']}",
            )
        ]
        for field, (icon, label, _) in PART_FIELDS.items()
    ]
    kb.append(
        [
            InlineKeyboardButton(
                "🗑 Remove",
                callback_data=f"troubleshooter:part_confirm_del:{part['id']}",
            )
        ]
    )
    kb.append(
        [
            InlineKeyboardButton(
                "🔍 Search Parts", callback_data="troubleshooter:parts_search"
            ),
            InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home"),
        ]
    )
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
