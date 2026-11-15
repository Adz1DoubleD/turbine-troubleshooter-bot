from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from troubleshooter.db import (
    user_notifications_get,
    user_notifications_toggle,
)
from troubleshooter.helpers import escape_markdown
from troubleshooter.settings import SETTINGS

from ..tools import alert_markup
from . import handle_block


async def button_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    context.user_data["state"] = None
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    if query.data == "troubleshooter:notifications:toggle":
        enabled = await user_notifications_toggle(user_id)
    else:
        enabled = await user_notifications_get(user_id)

    status = "🔔 *On*" if enabled else "🔕 *Off*"

    kb = [
        [
            InlineKeyboardButton(
                "🔕 Turn Off Notifications" if enabled else "🔔 Turn On Notifications",
                callback_data="troubleshooter:notifications:toggle",
            )
        ],
        [
            InlineKeyboardButton(
                "💬 Send Feedback", callback_data="troubleshooter:feedback"
            )
        ],
    ]
    if not admin:
        kb.append(
            [InlineKeyboardButton("🙋 Request Admin", callback_data="admin:request")]
        )
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back:troubleshooter")])

    await query.edit_message_text(
        f"👤 *User Menu*\n\n"
        f"*Code Update Notifications:* {status}\n"
        f"_Announcements from the admin always come through._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def button_alert_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    enabled = await user_notifications_toggle(query.from_user.id)
    await query.edit_message_reply_markup(reply_markup=alert_markup(enabled))
    await query.answer("🔔 Notifications on" if enabled else "🔕 Notifications off")


async def button_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "troubleshooter:feedback"
    context.user_data["last_msg_id"] = query.message.message_id
    await query.edit_message_text(
        "💬 *Send Feedback*\n\nType your message and it will be sent to the admin:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Cancel", callback_data="troubleshooter:user_menu"
                    )
                ]
            ]
        ),
    )


async def handle_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
):
    user = update.effective_user
    name = f"@{user.username}" if user.username else user.full_name
    await context.bot.send_message(
        chat_id=SETTINGS.alerts_chat_id,
        text=(
            f"💬 *Feedback for Troubleshooter Bot*\n\n"
            f"From: {escape_markdown(name)}\n\n{escape_markdown(text)}"
        ),
        parse_mode="Markdown",
    )
    context.user_data["state"] = None
    block = await handle_block(context)
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=context.user_data.get("last_msg_id"),
        text=f"✅ *Feedback sent!*\n\n{block['text']}",
        reply_markup=block["reply_markup"],
        parse_mode="Markdown",
    )


LOCKED_TEXT = (
    "🔒 *{name} Bot*\n\nAccess is by approval. Tap below to ask the admin for access."
)
LOCKED_MARKUP = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "🙋 Request Access", callback_data="troubleshooter:access_request"
            )
        ]
    ]
)


async def button_request_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    pending = context.bot_data.setdefault("pending_access_requests", {})
    if user.id in pending:
        await query.answer("⏳ Your request is already waiting.", show_alert=True)
        return

    name = f"@{user.username}" if user.username else user.full_name
    pending[user.id] = name

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Deny", callback_data=f"access:deny:{user.id}"),
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"access:approve:{user.id}"
                ),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=SETTINGS.alerts_chat_id,
        text=f"🔑 *Troubleshooter Access Request*\n\nFrom: {escape_markdown(name)}\nID: `{user.id}`",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    await query.answer("✅ Your request has been sent to the admin.", show_alert=True)


async def button_request_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if context.user_data.get("is_admin"):
        await query.answer("You already have admin access.", show_alert=True)
        block = await handle_block(context)
        await query.edit_message_text(
            block["text"],
            reply_markup=block["reply_markup"],
            parse_mode=block.get("parse_mode", "Markdown"),
        )
        return
    pending = context.bot_data.setdefault("pending_admin_requests", {})
    if user.id in pending:
        await query.answer("⏳ Your request is already waiting.", show_alert=True)
        return

    name = f"@{user.username}" if user.username else user.full_name
    pending[user.id] = name

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Deny", callback_data=f"admin:deny:{user.id}"),
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"admin:approve:{user.id}"
                ),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=SETTINGS.alerts_chat_id,
        text=f"🙋 *Troubleshooter Admin Request*\n\nFrom: {escape_markdown(name)}\nID: `{user.id}`",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    await query.answer("✅ Your request has been sent to the admin.", show_alert=True)
