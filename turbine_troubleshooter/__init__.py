import logging
import os

import sentry_sdk
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from turbine_troubleshooter.db import close_db, init_troubleshooter_db, user_add
from turbine_troubleshooter.helpers import (
    error_handler,
    error_handler_noise_filter,
    is_test_mode,
)

from .blocks import handle_block
from .blocks.admin import broadcast as admin_broadcast
from .blocks.admin import files as admin_files
from .blocks.admin import imports as admin_imports
from .blocks.user import LOCKED_MARKUP, LOCKED_TEXT
from .buttons import handle_button
from .helpers import set_user_roles
from .notify import send_notification_troubleshooter
from .settings import ENV_VARS, SETTINGS, setup
from .text_input import handle_text_input
from .weather import get_windquest_service, weather_block

application = None

__all__ = [
    "get_windquest_service",
    "handle_block",
    "handle_button",
    "handle_text_input",
    "start_troubleshooter_bot",
    "stop_troubleshooter_bot",
    "weather_block",
]


async def start_troubleshooter_bot(
    share_with: Application | None = None, env_prefix: str | None = None, **options
) -> Application:
    """Start the troubleshooter's own bot and return its Application.

    share_with: a host's Application, so the host can show the troubleshooter's
    menus and weather too.
    env_prefix: prefix for its environment variables, "TROUBLESHOOTER_" inside a
    host and none on its own.
    options: settings that override the environment, such as owner_id,
    alerts_chat_id, timezone, files_dir or test_mode.
    """
    global application
    if env_prefix is None:
        env_prefix = "" if share_with is None else "TROUBLESHOOTER_"
    setup(env_prefix, **options)
    missing = [
        f"{env_prefix}{ENV_VARS[name]}"
        for name in ("token", "owner_id", "db_url")
        if not vars(SETTINGS)[name]
    ]
    if missing:
        raise ValueError(f"Troubleshooter needs these settings: {', '.join(missing)}")
    if not SETTINGS.alerts_chat_id:
        SETTINGS.alerts_chat_id = SETTINGS.owner_id

    os.environ.setdefault("PTB_TIMEDELTA", "1")
    logging.getLogger("telegram").addFilter(error_handler_noise_filter)
    logging.getLogger("httpx").addFilter(error_handler_noise_filter)

    application = Application.builder().token(SETTINGS.token).build()
    application.bot_data["is_troubleshooter"] = True

    await init_troubleshooter_db(application)
    shared = {
        "codes": {},
        "parts": [],
        "io_boards": {},
        "troubleshooter_admins": {},
        "troubleshooter_approved": set(),
        "pending_access_requests": {},
        "pending_admin_requests": {},
        "pending_delete_requests": {},
    }
    for key, default in shared.items():
        value = application.bot_data.setdefault(key, default)
        if share_with is not None:
            share_with.bot_data[key] = value

    application.add_handler(CommandHandler("start", _command_handler))
    application.add_handler(CallbackQueryHandler(_callback_handler))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.CHANNEL_POSTS,
            _text_handler,
        )
    )
    application.add_handler(
        MessageHandler(
            (filters.Document.ALL | filters.PHOTO) & ~filters.UpdateType.CHANNEL_POSTS,
            _file_handler,
        )
    )
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()
    try:
        await admin_broadcast.offer_update_note(application)
    except Exception as e:
        sentry_sdk.capture_exception(e)
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    mode = "test mode" if is_test_mode() else "live"
    print(
        f"🚀 Troubleshooter running on its own bot @{application.bot.username} ({mode})"
    )
    return application


async def stop_troubleshooter_bot() -> None:
    """Stop the troubleshooter's bot and close its database connections."""
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


async def _command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def _callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await handle_button(update, context)


async def _text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or context.user_data is None:
        return
    await set_user_roles(context, update.effective_user.id)
    if not context.user_data["is_approved"]:
        return
    await handle_text_input(update, context)


async def _file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or context.user_data is None:
        return
    await set_user_roles(context, update.effective_user.id)
    if (context.user_data.get("state") or "").startswith("troubleshooter:import:"):
        await admin_imports.handle_file(update, context)
    elif context.user_data.get("is_admin"):
        await admin_files.handle_file(update, context)
