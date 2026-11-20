"""Sending feedback to the owner."""

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..notify import send_notification_troubleshooter

MAX_FEEDBACK = 1000


async def button_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "troubleshooter:feedback"
    context.user_data["last_msg_id"] = query.message.message_id
    await query.edit_message_text(
        "💬 *Feedback*\n\nWhat would you like to tell the admins? "
        "Send it as a message, up to 1,000 characters.\n\n"
        "_For example: advice that's out of date, or a manual that's missing._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancel", callback_data="troubleshooter:home")]]
        ),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    context.user_data["state"] = None
    if not text:
        status = "⚠️ Nothing was sent. Tap 💬 Feedback and type your message."
    else:
        try:
            await send_notification_troubleshooter(
                update.effective_user, "feedback", message=text[:MAX_FEEDBACK]
            )
            status = "✅ Thanks, sent to the admins."
        except Exception as e:
            sentry_sdk.capture_exception(e)
            status = "⚠️ Couldn't send it just now. Please try again later."

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")]]
    )
    msg_id = context.user_data.get("last_msg_id")
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=msg_id,
                text=status,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=status, reply_markup=reply_markup
    )
