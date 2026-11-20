"""Looking up a turbine's serial number and IP address."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..helpers import find_wtg
from ..settings import SETTINGS


async def button_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["state"] = "troubleshooter:wtg_search"
    context.user_data["last_msg_id"] = query.message.message_id
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back ", callback_data="troubleshooter:home")]]
    )
    example = f"`{SETTINGS.wtg_prefix}A10` or `A10`" if SETTINGS.wtg_prefix else "`A10`"
    await query.edit_message_text(
        f"🔍 *Search WTG Serials*\n\nPlease enter the WTG number (e.g. {example}):",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_data = context.user_data
    user_data["state"] = None
    wtg, info = find_wtg(text)

    if info:
        response = (
            f"🔢 *WTG Serial - {wtg}*\n\nSerial: `{info['serial']}`\nIP: `{info['ip']}`"
        )
    else:
        safe = text.replace("`", "")[:20]
        response = f"⚠️ *WTG Not Found*\n\nNo data for `{safe}`"

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔢 Another WTG", callback_data="troubleshooter:wtg_search"
                )
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")],
        ]
    )
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=user_data.get("last_msg_id"),
        text=response,
        parse_mode="Markdown",
        reply_markup=kb,
    )
