from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    delete_entry,
    fault_code_add,
)
from turbine_troubleshooter.helpers import escape_markdown

from ...tools import send_notification_troubleshooter, user_is_admin
from . import handle_block, local_now


async def button_code_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    await query.answer()

    context.user_data["state"] = "troubleshooter:code_add:code"
    context.user_data["last_msg_id"] = query.message.message_id
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back ", callback_data="troubleshooter:admin_menu")]]
    )
    await query.edit_message_text(
        "➕ *Add New Fault Code*\n\nStep 1: Please enter the *Error Code*:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def button_code_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    data = query.data
    code_to_del = data.split(":")[-1]

    if await delete_entry("codes", "code", code_to_del):
        if code_to_del in context.bot_data.get("codes", {}):
            del context.bot_data["codes"][code_to_del]
        display_text = f"✅ Code `{code_to_del}` has been removed."
        await send_notification_troubleshooter(
            query.from_user, "code_deleted", code_to_del
        )
    else:
        display_text = f"⚠️ Code `{code_to_del}` was not found in the database."

    return display_text


async def button_code_delete_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    data = query.data
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    code_to_del = data.split(":")[-1]
    keyboard = [
        [
            InlineKeyboardButton("❌ No, Cancel", callback_data="back:troubleshooter"),
            InlineKeyboardButton(
                "✅ Yes, Delete",
                callback_data=f"troubleshooter:code_delete:{code_to_del}",
            ),
        ]
    ]
    await query.edit_message_text(
        f"⚠️ *Are you sure?*\n\nYou are about to delete code: `{code_to_del}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_code_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    data = query.data
    code_id = data.split(":")[-1]
    existing = context.bot_data.get("codes", {}).get(code_id)

    if not existing:
        await query.answer(
            "❌ Code not found — it may have been removed.", show_alert=True
        )
        return

    context.user_data["code_edit_buffer"] = existing.copy()
    context.user_data["last_msg_id"] = query.message.message_id

    await handle_code_edit(context, query.message.chat_id, query.message.message_id)


async def button_code_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    data = query.data
    field = data.split(":")[2]
    context.user_data["state"] = f"troubleshooter:code_await_edit:{field}"
    current_val = escape_markdown(context.user_data["code_edit_buffer"][field] or "")

    await query.edit_message_text(
        f"✏️ *Updating {field.capitalize()}*\n\n"
        f"*Current:* {current_val}\n\n"
        f"Please enter the new details: (Note: Data will be over written, please copy paste anything above if you want to keep it)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="back:troubleshooter")]]
        ),
    )


async def button_code_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    is_admin = user_is_admin(context)

    if not is_admin:
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    entry = context.user_data.get("code_edit_buffer")
    if not entry:
        return

    user = query.from_user
    editor = f"@{user.username}" if user.username else user.full_name
    entry["edited_by"] = editor
    edited_at = local_now().strftime("%Y-%m-%d %H:%M")

    await fault_code_add(**entry, edited_at=edited_at)

    entry["edits"] = (entry.get("edits") or []) + [{"by": editor, "at": edited_at}]
    context.bot_data["codes"][entry["code"]] = entry
    context.user_data.pop("code_edit_buffer", None)

    await send_notification_troubleshooter(
        user,
        "code_edited",
        entry["code"],
        entry.get("advice"),
        entry.get("parts"),
    )

    return "✅ *Saved*", entry["code"]


async def handle_code_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: str
):
    user_data = context.user_data
    msg_id = user_data.get("last_msg_id")
    chat_id = update.effective_chat.id

    prompt = None

    if state == "troubleshooter:code_add:code":
        existing_codes = context.bot_data.get("codes", {})

        if text in existing_codes:
            match = existing_codes[text]
            response = (
                f"⚠️ *Fault Code {escape_markdown(text)} already exists!*\n\n"
                f"*Advice:*\n{escape_markdown(match['advice'])}\n\n"
                f"*Parts:*\n{escape_markdown(match['parts'])}"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📝 Edit",
                        callback_data=f"troubleshooter:code_edit:{match['code']}",
                    ),
                    InlineKeyboardButton(
                        "🗑 Remove",
                        callback_data=f"troubleshooter:code_confirm_del:{match['code']}",
                    ),
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="back:troubleshooter")],
            ]

            user_data["state"] = None
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=response,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        user_data["new_entry"] = {"code": text}
        user_data["state"] = "troubleshooter:code_add:advice"
        prompt = f"✅ Code: `{text}`\n\nStep 2: Enter the *Advice/Solution*:"

    elif state == "troubleshooter:code_add:advice":
        user_data["new_entry"]["advice"] = text
        user_data["state"] = "troubleshooter:code_add:parts"
        prompt = "Step 3: Enter the *Suggested Parts* (or type 'None'):"

    elif state == "troubleshooter:code_add:parts":
        user = update.effective_user
        name = f"@{user.username}" if user.username else user.full_name

        entry = user_data["new_entry"]
        entry["parts"] = text
        entry["added_by"] = name
        entry["added_at"] = local_now()

        entry["id"] = await fault_code_add(**entry)
        context.bot_data["codes"][entry["code"]] = entry
        res_text = f"✅ *Success!*\n\nCode `{entry['code']}` added to DB."

        await send_notification_troubleshooter(
            user, "code_added", entry["code"], entry["advice"], entry["parts"]
        )

        user_data["state"] = None
        await handle_block(update, context, status=res_text)
        return

    if msg_id and prompt:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back ", callback_data="back:troubleshooter")]]
        )
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=prompt,
            parse_mode="Markdown",
            reply_markup=kb,
        )


async def handle_code_edit(
    context: ContextTypes.DEFAULT_TYPE, chat_id, msg_id, updated=False
):
    entry = context.user_data.get("code_edit_buffer")
    if not entry:
        return

    status_line = (
        "Field updated! Select another or finish:"
        if updated
        else "Select a field to modify:"
    )

    text = (
        f"📝 *Editing Code:* `{entry['code']}`\n\n"
        f"*Advice:*\n{escape_markdown(entry['advice'] or '')}\n\n"
        f"*Parts:*\n{escape_markdown(entry['parts'] or '')}\n\n"
        f"{status_line}"
    )

    kb = [
        [
            InlineKeyboardButton(
                "💡 Change Advice",
                callback_data="troubleshooter:code_edit_field:advice",
            )
        ],
        [
            InlineKeyboardButton(
                "🔧 Change Parts", callback_data="troubleshooter:code_edit_field:parts"
            )
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="back:troubleshooter"),
            InlineKeyboardButton(
                "✅ Finish & Save", callback_data="troubleshooter:code_edit_save"
            ),
        ],
    ]

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )
