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
from turbine_troubleshooter.settings import SETTINGS

from ...helpers import user_is_admin
from ...notify import send_notification_troubleshooter
from . import handle_block, local_now
from .changes import ask_owner_to_delete

PART_FIELDS = {
    "part_no": ("🔢", "", 20),
    "stock_no": ("🏷️", "", 20),
    "location": ("📍", "", 40),
    "description": ("📝", "Description", 160),
}
OPTIONAL_FIELDS = ("stock_no", "location")


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
        "🔩 *Add Spare Part*\n\n"
        f"Step 1: Enter the *{escape_markdown(SETTINGS.part_no_label)}*:",
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
    label = label or getattr(SETTINGS, f"{field}_label")
    current = escape_markdown(part.get(field) or "") or "_None_"
    clear_hint = "\n_Send_ `-` _to clear it._" if field in OPTIONAL_FIELDS else ""

    context.user_data["state"] = f"troubleshooter:part_await_edit:{field}:{part_id}"
    context.user_data["last_msg_id"] = query.message.message_id

    await query.edit_message_text(
        f"✏️ *Updating {escape_markdown(label)}*\n\n"
        f"*Current:* {current}\n\n"
        f"Enter the new {escape_markdown(label)} (max {limit} characters):"
        f"{clear_hint}",
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
    assert user_data is not None
    parts = context.bot_data.setdefault("parts", [])

    if state == "troubleshooter:part_add:part_no":
        part_no = text.strip().upper()
        existing = [p for p in parts if p["part_no"] == part_no]

        if existing:
            user_data["state"] = None
            lines = "\n".join(
                f"• {escape_markdown(p['description'])}" for p in existing
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
            text=f"✅ {escape_markdown(SETTINGS.part_no_label)}: `{part_no}`\n\n"
            "Step 2: Enter the *Description*:",
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

    if state in (
        "troubleshooter:part_add:description",
        "troubleshooter:part_add:stock_no",
    ):
        if state.endswith("description"):
            user_data["new_part"]["description"] = text.strip()[:160]
            step, field = 3, "stock_no"
        else:
            stock_no = text.strip().upper()
            user_data["new_part"]["stock_no"] = "" if stock_no == "-" else stock_no[:20]
            step, field = 4, "location"
        user_data["state"] = f"troubleshooter:part_add:{field}"
        label = getattr(SETTINGS, f"{field}_label")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=user_data.get("last_msg_id"),
            text=f"Step {step}: Enter the *{escape_markdown(label)}*, "
            "or `-` if there isn't one:",
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
    location = text.strip().upper()
    entry["location"] = "" if location == "-" else location[:40]
    user_data["state"] = None

    user = update.effective_user
    added_by = f"@{user.username}" if user.username else user.full_name

    new_id = await part_add(
        entry["part_no"],
        entry["description"],
        added_by=added_by,
        stock_no=entry.get("stock_no"),
        location=entry["location"],
    )
    if new_id:
        parts.append({"id": new_id, "added_by": added_by, "edits": [], **entry})
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
    assert user_data is not None
    user_data["state"] = None
    _, _, field, raw_id = state.split(":")
    part_id = int(raw_id)

    part = _find_part(context, part_id)
    if not part:
        await handle_block(update, context, status="❌ Part not found.")
        return

    value = text.strip()
    if field != "description":
        value = value.upper()
    if field in OPTIONAL_FIELDS and value == "-":
        value = ""
    value = value[: PART_FIELDS[field][2]]

    parts = context.bot_data.get("parts", [])
    label = PART_FIELDS[field][1] or getattr(SETTINGS, f"{field}_label")
    old_value = part.get(field) or ""
    user = update.effective_user
    editor = f"@{user.username}" if user.username else user.full_name
    edited_at = local_now().strftime("%Y-%m-%d %H:%M")

    if not value and field not in OPTIONAL_FIELDS:
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

    owner = is_owner(query.from_user.id)
    await query.edit_message_text(
        f"⚠️ *Are you sure?*\n\nDelete `{part['part_no']}` – "
        f"{escape_markdown(part['description'])}"
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
    stock_no = f"`{part['stock_no']}`" if part.get("stock_no") else "_None_"
    location = escape_markdown(part["location"]) if part.get("location") else "_None_"
    text = (f"{status}\n\n" if status else "") + (
        f"🔩 *Edit Part*\n\n"
        f"*{escape_markdown(SETTINGS.part_no_label)}:* `{part['part_no']}`\n"
        f"*{escape_markdown(SETTINGS.stock_no_label)}:* {stock_no}\n"
        f"*{escape_markdown(SETTINGS.location_label)}:* {location}\n"
        f"*Description:* {escape_markdown(part['description'])}\n\n"
        f"Select a field to change:"
    )
    kb = [
        [
            InlineKeyboardButton(
                f"{icon} {label or getattr(SETTINGS, f'{field}_label')}",
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
