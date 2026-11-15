from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from troubleshooter.db import db_export, db_tables, setting_toggle
from troubleshooter.helpers import error_kb, is_owner
from troubleshooter.settings import SETTINGS

from ...tools import user_is_admin


async def button_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    table = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id
    rows = await db_tables(table)
    if not rows:
        text = f"Unknown table: {table}" if rows is None else f"{table} is empty."
        await context.bot.send_message(chat_id, text, reply_markup=error_kb())
        return

    await context.bot.send_document(
        chat_id=chat_id,
        document=db_export(rows),
        filename=f"{table}_{datetime.now():%Y%m%d_%H%M}.csv",
        caption=(
            f"📤 *{table.capitalize()} table exported*\n\n"
            f"{len(rows)} rows · {len(rows[0])} columns"
        ),
        parse_mode="Markdown",
        reply_markup=error_kb(),
    )


EXPORT_LABELS = {
    "codes": "Codes",
    "parts": "Spare Parts",
    "io_boards": "IO Boards",
    "users": "Users",
}


async def button_export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton(f"📤 {label}", callback_data=f"export:{table}")]
        for table, label in EXPORT_LABELS.items()
    ]
    kb.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
    )

    await query.edit_message_text(
        "📤 *Export*\n\nPick a table to download as CSV:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


NOTIFY_LABELS = {"added": "➕ Added", "edited": "✏️ Edited", "deleted": "🗑️ Deleted"}


async def button_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    verb = query.data.removeprefix("troubleshooter:notify_users").lstrip(":")
    if verb in NOTIFY_LABELS:
        await setting_toggle(f"notify_{verb}")

    kb = [
        [
            InlineKeyboardButton(
                f"{'✅' if int(SETTINGS.notify_settings.get(f'notify_{v}', 1)) else '❌'}"
                f" {label}",
                callback_data=f"troubleshooter:notify_users:{v}",
            )
        ]
        for v, label in NOTIFY_LABELS.items()
    ]
    kb.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
    )

    await query.edit_message_text(
        "🔔 *Notify Users*\n\n"
        "When a code or part is added, edited or deleted, users are told if it's ✅. "
        "If it's ❌, only admins are told.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


def local_now():
    return datetime.now(ZoneInfo(SETTINGS.timezone)).replace(tzinfo=None)


async def handle_block(
    update: Update, context: ContextTypes.DEFAULT_TYPE, status: str | None = None
):
    query = update.callback_query
    is_admin = user_is_admin(context)
    if not is_admin:
        if query:
            await query.answer(
                "⚠️ Unauthorized: Admin access required.", show_alert=True
            )
        return

    text = status or "⚙️ *Admin Panel*\n\nSelect an option below:"

    user = update.effective_user
    owner = bool(user and is_owner(user.id))

    pending = sum(
        len(context.bot_data.get(f"pending_{kind}_requests", {}))
        for kind in ("access", "admin")
    )
    users_label = (
        f"👥 Users (⏳ {pending} pending)" if owner and pending else "👥 Users"
    )

    kb = [
        [InlineKeyboardButton("➕ Add Code", callback_data="troubleshooter:code_add")],
        [InlineKeyboardButton("🔩 Add Part", callback_data="troubleshooter:part_add")],
        [InlineKeyboardButton(users_label, callback_data="troubleshooter:user_list")],
        [InlineKeyboardButton("📤 Export", callback_data="troubleshooter:export_menu")],
    ]

    if owner:
        kb.append(
            [
                InlineKeyboardButton(
                    "📢 Broadcast", callback_data="troubleshooter:broadcast"
                )
            ]
        )
        kb.append(
            [
                InlineKeyboardButton(
                    "🔔 Notify Users", callback_data="troubleshooter:notify_users"
                )
            ]
        )

    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back:troubleshooter")])

    if query:
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get("last_msg_id"),
            text=text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
