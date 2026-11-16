import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from troubleshooter.db import close_db, init_troubleshooter_db, user_add
from troubleshooter.helpers import (
    close_message,
    error_handler,
    error_handler_noise_filter,
    error_kb,
)

from . import weather
from .blocks import admin as admin_menu
from .blocks import codes, handle_block, io_boards, parts, suggest, user, wtg
from .blocks.admin import broadcast as admin_broadcast
from .blocks.admin import codes as admin_codes
from .blocks.admin import parts as admin_parts
from .blocks.admin import users as admin_users
from .blocks.user import LOCKED_MARKUP, LOCKED_TEXT
from .settings import ENV_VARS, SETTINGS, setup
from .tools import (
    get_troubleshooter_content,
    send_notification_troubleshooter,
    set_user_roles,
)

logging.getLogger("telegram").addFilter(error_handler_noise_filter)
logging.getLogger("httpx").addFilter(error_handler_noise_filter)
application = None


async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.delete()
    except Exception:
        pass
    user = update.effective_user

    username = user.username if user.username else user.full_name
    new = await user_add(user.id, username)
    if new:
        await send_notification_troubleshooter(user)
    await set_user_roles(context, update.effective_user.id)
    if not context.user_data["is_approved"]:
        await update.message.reply_text(
            LOCKED_TEXT.format(name=SETTINGS.name),
            reply_markup=LOCKED_MARKUP,
            parse_mode="Markdown",
        )
        return
    block = await handle_block(context)
    await update.message.reply_text(
        block["text"],
        reply_markup=block["reply_markup"],
        parse_mode=block.get("parse_mode", "Markdown"),
    )


async def callback_handler(update: Update, context):
    query = update.callback_query
    await set_user_roles(context, query.from_user.id)
    data = query.data

    if not context.user_data["is_approved"] and data not in (
        "cancel",
        "troubleshooter:access_request",
    ):
        await query.answer()
        try:
            await query.edit_message_text(
                LOCKED_TEXT.format(name=SETTINGS.name),
                reply_markup=LOCKED_MARKUP,
                parse_mode="Markdown",
            )
        except BadRequest:
            pass
        return

    if data == "cancel":
        context.user_data["state"] = None
        await query.answer()
        await close_message(query, reopen="back:troubleshooter")
        return

    if data == "back:troubleshooter":
        await query.answer()
        context.user_data["state"] = None
        block = await handle_block(context)
        if query.message.photo or query.message.document:
            try:
                await query.message.delete()
            except Exception:
                try:
                    await query.edit_message_caption(
                        caption=block["text"],
                        reply_markup=block["reply_markup"],
                        parse_mode=block.get("parse_mode", "Markdown"),
                    )
                except Exception:
                    pass
                return
            await query.message.reply_text(
                block["text"],
                reply_markup=block["reply_markup"],
                parse_mode=block.get("parse_mode", "Markdown"),
            )
        else:
            await query.edit_message_text(
                block["text"],
                reply_markup=block["reply_markup"],
                parse_mode=block.get("parse_mode", "Markdown"),
            )
        return

    await handle_button(update, context)
    try:
        await query.answer()
    except BadRequest:
        pass


async def text_handler(update: Update, context):
    if update.effective_user is None or context.user_data is None:
        return
    await set_user_roles(context, update.effective_user.id)
    if not context.user_data["is_approved"]:
        return
    await handle_text_input(update, context)


async def file_handler(update: Update, context):
    if update.effective_user is None or context.user_data is None:
        return
    await set_user_roles(context, update.effective_user.id)
    if not context.user_data["is_approved"]:
        return
    await suggest.handle_file(update, context)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    content = get_troubleshooter_content()

    if data in content:
        item = content[data]

        if item["type"] == "menu":
            if data == "troubleshooter:ioboard":
                await query.edit_message_text(
                    "Select an IO Board:", reply_markup=io_boards.board_menu()
                )
            elif item.get("items"):
                buttons = [
                    InlineKeyboardButton(content[k]["title"], callback_data=k)
                    for k in item["items"]
                ]
                kb = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
                kb.append(
                    [
                        InlineKeyboardButton(
                            "🔙 Back",
                            callback_data=item.get("parent") or "back:troubleshooter",
                        )
                    ]
                )
                text = f"*{item['title']}*\n\nSelect an option:"
                if query.message.text:
                    await query.edit_message_text(
                        text,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb),
                    )
                else:
                    await close_message(query)
                    await context.bot.send_message(
                        query.message.chat_id,
                        text,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb),
                    )
            return

        content_body = item.get("content", "")
        caption = f"*{item['title']}*\n\n{content_body}"
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data=item.get("parent") or "back:troubleshooter",
                    )
                ]
            ]
        )

        files = item.get("file")
        files = files if isinstance(files, list) else [files]
        if item["type"] in ("document", "photo") and any(
            isinstance(f, Path) and not f.is_file() for f in files
        ):
            text = f"*{item['title']}*\n\n📄 This document isn't available right now."
            if query.message.text:
                await query.edit_message_text(
                    text, parse_mode="Markdown", reply_markup=kb
                )
            else:
                await close_message(query)
                await context.bot.send_message(
                    query.message.chat_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            return

        if item["type"] == "text":
            await query.edit_message_text(
                caption, parse_mode="Markdown", reply_markup=kb
            )

        elif item["type"] == "document":
            await close_message(query)

            for i, doc in enumerate(files):
                is_last = i == len(files) - 1
                await query.message.reply_document(
                    document=doc,
                    caption=caption if is_last else None,
                    parse_mode="Markdown",
                    reply_markup=kb if is_last else error_kb(None),
                )

        elif item["type"] == "photo":
            await close_message(query)
            await query.message.reply_photo(
                photo=item["file"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=kb,
            )
        return

    if data.startswith("troubleshooter:ioboard:"):
        await io_boards.button_board(update, context)

    elif data == "troubleshooter:code_search":
        await codes.button_search(update, context)

    elif data.startswith("troubleshooter:code_search:"):
        await codes.button_page(update, context)

    elif weather.is_enabled() and data.startswith("troubleshooter:weather"):
        await weather.handle_button(update, context)

    elif data == "troubleshooter:wtg_search":
        await wtg.button_search(update, context)

    elif data == "troubleshooter:parts_search":
        await parts.button_search(update, context)

    elif admin and data == "troubleshooter:part_add":
        await admin_parts.button_part_add(update, context)

    elif data in ("troubleshooter:user_menu", "troubleshooter:notifications:toggle"):
        await user.button_menu(update, context)

    elif data.startswith("troubleshooter:suggest"):
        await suggest.handle_button(update, context)

    elif data == "admin:request":
        await user.button_request_admin(update, context)

    elif data == "troubleshooter:access_request":
        await user.button_request_access(update, context)

    elif data.startswith("access:approve:"):
        await admin_users.button_access_approve(update, context)

    elif data.startswith("access:deny:"):
        await admin_users.button_access_deny(update, context)

    elif data.startswith("admin:approve:"):
        await admin_users.button_admin_approve(update, context)

    elif data.startswith("admin:deny:"):
        await admin_users.button_admin_deny(update, context)

    elif data == "troubleshooter:notifications:alert":
        await user.button_alert_toggle(update, context)

    elif admin and data.startswith("troubleshooter:code_confirm_del:"):
        await admin_codes.button_code_delete_confirm(update, context)

    elif admin and data.startswith("troubleshooter:code_delete:"):
        status = await admin_codes.button_code_delete(update, context)
        if status:
            block = await handle_block(context)
            await query.edit_message_text(
                text=f"{status}\n\n{block['text']}",
                reply_markup=block["reply_markup"],
                parse_mode="Markdown",
            )

    elif admin and data.startswith("troubleshooter:code_edit:"):
        await admin_codes.button_code_edit(update, context)

    elif admin and data.startswith("troubleshooter:code_edit_field:"):
        await admin_codes.button_code_edit_field(update, context)

    elif admin and data == "troubleshooter:code_edit_save":
        result = await admin_codes.button_code_edit_save(update, context)
        if result:
            status, code = result
            match = context.bot_data.get("codes", {}).get(code)
            if match:
                text, markup = await codes.code_view(match, admin)
                await query.edit_message_text(
                    f"{status}\n\n{text}", parse_mode="Markdown", reply_markup=markup
                )
            else:
                block = await handle_block(context)
                await query.edit_message_text(
                    text=f"{status}\n\n{block['text']}",
                    reply_markup=block["reply_markup"],
                    parse_mode="Markdown",
                )

    elif admin and data.startswith("troubleshooter:user_list"):
        await admin_users.button_users_list(update, context)

    elif admin and data.startswith("troubleshooter:user:"):
        await admin_users.button_user_card(update, context)

    elif admin and data.startswith("troubleshooter:user_act:"):
        await admin_users.button_user_action(update, context)

    elif admin and data.startswith("troubleshooter:user_do:"):
        await admin_users.button_user_do(update, context)

    elif admin and data.startswith("troubleshooter:pending"):
        await admin_users.button_pending(update, context)

    elif admin and data == "troubleshooter:user_search":
        await admin_users.button_user_search(update, context)

    elif admin and data == "troubleshooter:export_menu":
        await admin_menu.button_export_menu(update, context)

    elif admin and data.startswith("export:"):
        await admin_menu.button_export(update, context)

    elif admin and data.startswith("troubleshooter:notify_users"):
        await admin_menu.button_notify(update, context)

    elif admin and data == "troubleshooter:admin_menu":
        await admin_menu.handle_block(update, context)

    elif admin and data == "troubleshooter:code_add":
        await admin_codes.button_code_add(update, context)

    elif admin and data.startswith("troubleshooter:broadcast"):
        await admin_broadcast.button_broadcast(update, context)

    elif admin and data.startswith("troubleshooter:part_edit:"):
        await admin_parts.button_part_edit(update, context)

    elif admin and data.startswith("troubleshooter:part_edit_field:"):
        await admin_parts.button_part_edit_field(update, context)

    elif admin and data.startswith("troubleshooter:part_confirm_del:"):
        await admin_parts.button_part_delete_confirm(update, context)

    elif admin and data.startswith("troubleshooter:part_delete:"):
        await admin_parts.button_part_delete(update, context)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_data = context.user_data
    state = user_data.get("state", "")
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    try:
        await update.message.delete()
    except Exception:
        pass

    if admin and state.startswith("troubleshooter:code_add:"):
        await admin_codes.handle_code_add(update, context, text, state)
        return

    if admin and state.startswith("troubleshooter:part_add:"):
        await admin_parts.handle_part_add(update, context, text, state)
        return

    if admin and state.startswith("troubleshooter:part_await_edit:"):
        await admin_parts.handle_part_edit(update, context, text, state)
        return

    if admin and state.startswith("troubleshooter:code_await_edit:"):
        field = state.split(":")[2]
        context.user_data["code_edit_buffer"][field] = text
        context.user_data["state"] = None

        await admin_codes.handle_code_edit(
            context,
            update.effective_chat.id,
            context.user_data.get("last_msg_id"),
            updated=True,
        )

    elif state == "troubleshooter:code_search":
        await codes.handle_search(update, context, text)

    elif state == "troubleshooter:wtg_search":
        await wtg.handle_search(update, context, text)

    elif state == "troubleshooter:parts_search":
        await parts.handle_search(update, context, text)

    elif state.startswith("troubleshooter:suggest:"):
        await suggest.handle_text(update, context, text)

    elif admin and state == "troubleshooter:user_search":
        await admin_users.handle_user_search(update, context, text)

    elif state == "troubleshooter:broadcast":
        await admin_broadcast.handle_broadcast(update, context, text)
        return


async def start_troubleshooter_bot(share_with=None, **options):
    global application
    setup(**options)
    missing = [
        ENV_VARS[name] for name in ("token", "owner_id") if not vars(SETTINGS)[name]
    ]
    if not (os.environ.get("TROUBLESHOOTER_DB_URL") or os.environ.get("JAWSDB_URL")):
        missing.append("TROUBLESHOOTER_DB_URL")
    if missing:
        raise ValueError(f"Troubleshooter needs these settings: {', '.join(missing)}")
    if not SETTINGS.alerts_chat_id:
        SETTINGS.alerts_chat_id = SETTINGS.owner_id

    application = Application.builder().token(SETTINGS.token).build()
    application.bot_data["is_troubleshooter"] = True

    await init_troubleshooter_db(application)
    shared = {
        "codes": {},
        "parts": [],
        "io_boards": {},
        "troubleshooter_admins": {},
        "troubleshooter_approved": set(),
        "pending_suggestions": {},
    }
    for key, default in shared.items():
        value = application.bot_data.setdefault(key, default)
        if share_with is not None:
            share_with.bot_data[key] = value

    application.add_handler(CommandHandler("start", command_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.CHANNEL_POSTS,
            text_handler,
        )
    )
    application.add_handler(
        MessageHandler(
            (filters.Document.ALL | filters.PHOTO) & ~filters.UpdateType.CHANNEL_POSTS,
            file_handler,
        )
    )
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("🚀 Troubleshooting Bot initialized and polling")
    return application


async def stop_troubleshooter_bot():
    global application
    if application is not None:
        if application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        if application._initialized:
            await application.shutdown()
        application = None
    await close_db()
