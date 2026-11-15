import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from troubleshooter.db import users_get
from troubleshooter.helpers import escape_markdown, is_owner

from ...tools import send_notification_troubleshooter
from . import handle_block


async def button_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_data = context.user_data

    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Unauthorized.", show_alert=True)
        return

    await query.answer()

    parts = query.data.split(":")
    choice = parts[2] if len(parts) > 2 else None

    if choice is None:
        kb = [
            [
                InlineKeyboardButton(
                    "📢 All Users", callback_data="troubleshooter:broadcast:all"
                )
            ],
            [
                InlineKeyboardButton(
                    "🛡️ Admins Only", callback_data="troubleshooter:broadcast:admins"
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 Choose User", callback_data="troubleshooter:broadcast:choose"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back", callback_data="troubleshooter:admin_menu"
                )
            ],
        ]
        await query.edit_message_text(
            "📢 *Broadcast*\n\nWho should receive it?",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
        return

    if choice == "choose":
        users = await users_get()

        buttons = [
            InlineKeyboardButton(
                f"{'🛡️ ' if u['is_admin'] else ''}"
                f"{'@' + u['username'] if u['username'] else u['user_id']}",
                callback_data=f"troubleshooter:broadcast:user:{u['user_id']}",
            )
            for u in users
        ]
        kb = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        kb.append(
            [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:broadcast")]
        )

        await query.edit_message_text(
            "👤 *Choose a user:*" if users else "👤 No users found.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
        return

    if choice == "user":
        audience = int(parts[3])
        try:
            match = next(
                (u for u in await users_get() if u["user_id"] == audience), None
            )
        except Exception as e:
            sentry_sdk.capture_exception(e)
            match = None
        label = (
            f"@{escape_markdown(match['username'])}"
            if match and match["username"]
            else f"user `{audience}`"
        )
    elif choice == "admins":
        audience, label = "admins", "all admins"
    else:
        audience, label = "all", "all registered users"

    user_data["state"] = "troubleshooter:broadcast"
    user_data["broadcast_audience"] = audience
    user_data["last_msg_id"] = query.message.message_id

    await query.edit_message_text(
        f"📢 *Broadcast Mode*\n\nEnter the message to send to {label}:",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Cancel", callback_data="troubleshooter:admin_menu"
                    )
                ]
            ]
        ),
        parse_mode="Markdown",
    )


async def handle_broadcast(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
):
    user_data = context.user_data

    if not is_owner(update.effective_user.id):
        return

    user_data["state"] = None
    audience = user_data.pop("broadcast_audience", "all")

    try:
        await update.message.delete()
    except Exception:
        pass

    success, blocked, successful_users = await send_notification_troubleshooter(
        action="broadcast", message=text, audience=audience
    )

    recipients_str = ", ".join(successful_users[:20])
    if len(successful_users) > 20:
        recipients_str += f" ...and {len(successful_users) - 20} more"
    elif not recipients_str:
        recipients_str = "None"

    await handle_block(
        update,
        context,
        status=(
            f"✅ *Broadcast Complete!*\n\n"
            f"• Successfully sent: `{success}`\n"
            f"• Blocked: `{blocked}`\n\n"
            f"👤 *Recipients:* {recipients_str}"
        ),
    )
