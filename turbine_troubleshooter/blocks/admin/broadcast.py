from importlib.metadata import PackageNotFoundError, version

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import setting_mark, user_get, users_get
from turbine_troubleshooter.helpers import escape_markdown, is_owner, is_test_mode
from turbine_troubleshooter.settings import SETTINGS
from turbine_troubleshooter.whats_new import WHATS_NEW

from ...tools import send_notification_troubleshooter
from . import handle_block

PICKER_PAGE_SIZE = 20


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
        users.sort(key=lambda u: (not u["username"], (u["username"] or "").lower()))
        pages = max((len(users) - 1) // PICKER_PAGE_SIZE + 1, 1)
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        page = min(page, pages - 1)
        shown = users[page * PICKER_PAGE_SIZE : (page + 1) * PICKER_PAGE_SIZE]

        buttons = [
            InlineKeyboardButton(
                f"{'🛡️ ' if u['is_admin'] else ''}"
                f"{'@' + u['username'] if u['username'] else u['user_id']}",
                callback_data=f"troubleshooter:broadcast:user:{u['user_id']}",
            )
            for u in shown
        ]
        kb = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    "◀️ Prev",
                    callback_data=f"troubleshooter:broadcast:choose:{page - 1}",
                )
            )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    "Next ▶️",
                    callback_data=f"troubleshooter:broadcast:choose:{page + 1}",
                )
            )
        if nav:
            kb.append(nav)
        kb.append(
            [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:broadcast")]
        )

        text = "👤 *Choose a user:*" if users else "👤 No users found."
        if pages > 1:
            text += f"\n\nPage {page + 1} of {pages}"
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
        return

    if choice == "user":
        audience = int(parts[3])
        try:
            match = await user_get(audience)
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


async def offer_update_note(application):
    try:
        current = version("turbine-troubleshooter-bot")
    except PackageNotFoundError:
        return
    note = WHATS_NEW.get(current)
    if (
        not note
        or is_test_mode()
        or str(SETTINGS.announce_updates).lower() in ("0", "false", "no", "off")
    ):
        return
    if not application.bot_data.get("troubleshooter_approved"):
        return
    if not await setting_mark(f"offered_{current}"):
        return
    await application.bot.send_message(
        SETTINGS.owner_id,
        f"📢 *What's new in {escape_markdown(SETTINGS.name)} {current}*\n\n"
        f"{escape_markdown(note)}\n\nSend this to everyone?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📢 Send to Everyone",
                        callback_data=f"troubleshooter:announce:send:{current}",
                    ),
                    InlineKeyboardButton(
                        "❌ Skip",
                        callback_data=f"troubleshooter:announce:skip:{current}",
                    ),
                ]
            ]
        ),
    )


async def button_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Only the owner can do that.", show_alert=True)
        return

    _, _, choice, current = query.data.split(":")
    note = WHATS_NEW.get(current)
    if choice != "send" or not note:
        await query.answer()
        await query.edit_message_text(f"❌ Skipped. The {current} note wasn't sent.")
        return
    if not await setting_mark(f"announced_{current}"):
        await query.answer("It's already been sent.", show_alert=True)
        return

    await query.answer("📢 Sending…")
    sent, blocked, _ = await send_notification_troubleshooter(
        query.from_user,
        "broadcast",
        message=f"What's new in {SETTINGS.name}:\n\n{note}",
    )
    await query.edit_message_text(
        f"📢 Sent the {current} update to {sent} users"
        + (f". {blocked} have blocked the bot." if blocked else ".")
    )
