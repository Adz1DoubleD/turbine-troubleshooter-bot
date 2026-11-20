"""The user menu: notifications and asking for access or admin rights."""

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    request_add,
    user_notifications_get,
    user_notifications_toggle,
)
from turbine_troubleshooter.helpers import escape_markdown
from turbine_troubleshooter.settings import SETTINGS

from ..notify import alert_markup
from . import handle_block


async def button_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
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
    ]
    if not admin:
        kb.append(
            [
                InlineKeyboardButton(
                    "🙋 Request Admin", callback_data="troubleshooter:admin:request"
                )
            ]
        )
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")])

    await query.edit_message_text(
        f"👤 *User Menu*\n\n"
        f"*Code Update Notifications:* {status}\n"
        f"_Announcements from the admin always come through._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def button_alert_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    enabled = await user_notifications_toggle(query.from_user.id)
    await query.edit_message_reply_markup(reply_markup=alert_markup(enabled))
    await query.answer("🔔 Notifications on" if enabled else "🔕 Notifications off")


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


async def button_request_access(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user
    pending = context.bot_data.setdefault("pending_access_requests", {})
    if user.id in pending:
        await query.answer("⏳ Your request is already waiting.", show_alert=True)
        return

    name = f"@{user.username}" if user.username else user.full_name
    pending[user.id] = name
    await _save_request(user.id, "access", name)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Deny", callback_data=f"troubleshooter:access:deny:{user.id}"
                ),
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"troubleshooter:access:approve:{user.id}",
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


async def button_request_admin(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
    await _save_request(user.id, "admin", name)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Deny", callback_data=f"troubleshooter:admin:deny:{user.id}"
                ),
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"troubleshooter:admin:approve:{user.id}",
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


async def _save_request(user_id: int, kind: str, name: str) -> None:
    try:
        await request_add(user_id, kind, name)
    except Exception as e:
        print(f"❌ [DB] Failed to save {kind} request: {e}")
        sentry_sdk.capture_exception(e)
