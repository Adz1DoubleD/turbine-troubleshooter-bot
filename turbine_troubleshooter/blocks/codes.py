"""Searching fault codes and showing their advice."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import get_neighbours
from turbine_troubleshooter.helpers import escape_markdown

from ..helpers import find_codes


async def code_view(match, admin):
    row_id = match.get("id")
    prev_id, next_id = (
        await get_neighbours(int(row_id), "codes", order_by="code")
        if row_id
        else (None, None)
    )

    def stamp(by, at):
        if isinstance(at, str):
            at = datetime.strptime(at, "%Y-%m-%d %H:%M")
        when = f" ({at:%d %b %Y})" if at else ""
        return f"{escape_markdown(by)}{when}"

    meta = ""
    if match.get("added_by"):
        meta += f"\n\n*Added by:* {stamp(match['added_by'], match.get('added_at'))}"

    edits = match.get("edits") or []
    if edits:
        names = ", ".join(stamp(e["by"], e.get("at")) for e in edits[-3:])
        more = f" +{len(edits) - 3} more" if len(edits) > 3 else ""
        meta += f"\n*Edited by:* {names}{more}"

    text = (
        f"*Fault Code:* `{match['code']}`\n\n"
        f"*Advice:*\n{escape_markdown(match['advice'] or '')}\n\n"
        f"*Parts:*\n{escape_markdown(match['parts'] or '')}"
        f"{meta}"
    )

    def page_button(label, target_id):
        if not target_id:
            return InlineKeyboardButton(" ", callback_data="ignore")
        return InlineKeyboardButton(
            label, callback_data=f"troubleshooter:code_search:{target_id}"
        )

    keyboard = [
        [
            page_button("⬅️ Prev", prev_id),
            InlineKeyboardButton(
                "🔍 Search", callback_data="troubleshooter:code_search"
            ),
            page_button("Next ➡️", next_id),
        ]
    ]

    if admin:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📝 Edit", callback_data=f"troubleshooter:code_edit:{match['code']}"
                ),
                InlineKeyboardButton(
                    "🗑 Remove",
                    callback_data=f"troubleshooter:code_confirm_del:{match['code']}",
                ),
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")]
    )

    return text, InlineKeyboardMarkup(keyboard)


async def button_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    target_id = query.data.split(":")[-1]
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    match = next(
        (
            c
            for c in context.bot_data.get("codes", {}).values()
            if str(c.get("id")) == target_id
        ),
        None,
    )

    if not match:
        await button_search(update, context)
        return

    text, markup = await code_view(match, admin)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)


async def button_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["state"] = "troubleshooter:code_search"
    context.user_data["last_msg_id"] = query.message.message_id
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back ", callback_data="troubleshooter:home")]]
    )
    await query.edit_message_text(
        "🔍 *Fault Code Search*\n\nPlease enter the error code you are looking for:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_data = context.user_data
    code_data = context.bot_data.get("codes", {})
    msg_id = user_data.get("last_msg_id")
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    user_data["state"] = None
    match = code_data.get(text.strip())

    if match:
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        response, reply_markup = await code_view(match, admin)
    else:
        results = find_codes(text, code_data)

        if results:
            response = (
                f"⚠️ *No exact match for* `{escape_markdown(text)}`\n\n"
                "Did you mean one of these?"
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🔧 {c['code']}",
                        callback_data=f"troubleshooter:code_search:{c['id']}",
                    )
                ]
                for c in results
            ]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔍 Try Again", callback_data="troubleshooter:code_search"
                    )
                ]
            )
            if admin:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "➕ Add Code", callback_data="troubleshooter:code_add"
                        )
                    ]
                )
            keyboard.append(
                [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")]
            )
        else:
            response = f"⚠️ *Code Not Found*\n\nNo results for fault code: `{escape_markdown(text)}`"
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔍 Try Again", callback_data="troubleshooter:code_search"
                    )
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:home")],
            ]
            if admin:
                keyboard.insert(
                    1,
                    [
                        InlineKeyboardButton(
                            "➕ Add Code", callback_data="troubleshooter:code_add"
                        )
                    ],
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
