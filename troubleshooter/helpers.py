import os
import re
import traceback

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest

from troubleshooter.settings import SETTINGS

ERROR_REPLY = "⚠️ Something went wrong. It's been logged."


def is_local():
    return "DYNO" not in os.environ


def is_owner(user_id) -> bool:
    chat_id = SETTINGS.owner_id
    if not chat_id:
        return False
    try:
        return int(user_id) == int(chat_id)
    except (TypeError, ValueError):
        return False


def escape_markdown(text):
    escape_chars = r"_*[`"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))


def error_kb(block=None):
    text = f"🔙 Back to {block.capitalize()}" if block else "❌ Close"
    callback = f"back:{block}" if block else "cancel"
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=callback)]])


async def close_message(query, title=None, reopen="back:troubleshooter"):
    title = title or f"🛠 *{SETTINGS.name} Bot*"
    try:
        await query.message.delete()
    except BadRequest:
        edit = (
            query.edit_message_text
            if query.message.text
            else query.edit_message_caption
        )
        markup = (
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Open Menu", callback_data=reopen)]]
            )
            if reopen
            else None
        )
        try:
            await edit(title, parse_mode="Markdown", reply_markup=markup)
        except BadRequest:
            pass


async def error_handler(update, context):
    error = context.error
    if any(noise.lower() in str(error).lower() for noise in SETTINGS.noise_filters):
        return

    if isinstance(update, Update):
        if update.edited_message:
            return
        if update.effective_message:
            try:
                await update.effective_message.reply_text(
                    ERROR_REPLY, reply_markup=error_kb()
                )
            except Exception:
                pass

    sentry_sdk.capture_exception(error)
    if is_local():
        traceback.print_exception(error)


def error_handler_noise_filter(record):
    msg = record.getMessage()
    return not any(n in msg for n in SETTINGS.noise_filters)
