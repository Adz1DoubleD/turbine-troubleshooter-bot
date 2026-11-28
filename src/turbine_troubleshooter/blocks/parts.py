"""Searching spare parts."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.helpers import escape_markdown
from turbine_troubleshooter.settings import SETTINGS

from ..helpers import find_parts


async def button_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    query = update.callback_query
    context.user_data["state"] = "troubleshooter:parts_search"
    context.user_data["last_msg_id"] = query.message.message_id
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")]]
    )
    await query.edit_message_text(
        "🔩 *Spare Parts*\n\nEnter a part name, "
        f"{escape_markdown(SETTINGS.part_no_label)} or "
        f"{escape_markdown(SETTINGS.stock_no_label)}:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    assert context.user_data is not None
    context.user_data["state"] = None
    msg_id = context.user_data.get("last_msg_id")
    results = find_parts(text, context.bot_data.get("parts", []))
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    if results:
        found = []
        for p in results:
            lines = [f"{escape_markdown(SETTINGS.part_no_label)}: `{p['part_no']}`"]
            if p.get("stock_no"):
                lines.append(
                    f"{escape_markdown(SETTINGS.stock_no_label)}: `{p['stock_no']}`"
                )
            if p.get("section"):
                lines.append(escape_markdown(p["section"]))
            found.append(
                f"*{escape_markdown(p['description'])}*\n"
                + "\n".join(
                    ("└ " if i == len(lines) - 1 else "├ ") + line
                    for i, line in enumerate(lines)
                )
            )
        response = f"🔩 *Spare Parts:* {escape_markdown(text)}\n\n" + "\n\n".join(found)
    else:
        response = f"⚠️ *No Parts Found*\n\nNo results for: `{escape_markdown(text)}`"

    keyboard = []
    if admin:
        edit = [
            InlineKeyboardButton(
                f"✏️ {p['part_no']}",
                callback_data=f"troubleshooter:part_edit:{p['id']}",
            )
            for p in results
            if p.get("id")
        ]
        keyboard += [edit[i : i + 2] for i in range(0, len(edit), 2)]
        keyboard.append(
            [
                InlineKeyboardButton(
                    "➕ Add Part", callback_data="troubleshooter:part_add"
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(
                "🔍 Search Again", callback_data="troubleshooter:parts_search"
            )
        ]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")]
    )
    reply_markup = InlineKeyboardMarkup(keyboard)

    if msg_id:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_id,
            text=response,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(
            response, parse_mode="Markdown", reply_markup=reply_markup
        )
