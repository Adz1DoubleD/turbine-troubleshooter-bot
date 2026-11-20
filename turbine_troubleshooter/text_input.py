"""Handles the replies the troubleshooter asks users to type."""

from telegram import Update
from telegram.ext import ContextTypes

from .blocks import codes, feedback, parts, wtg
from .blocks.admin import broadcast as admin_broadcast
from .blocks.admin import codes as admin_codes
from .blocks.admin import content as admin_content
from .blocks.admin import parts as admin_parts
from .blocks.admin import users as admin_users


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a typed reply the troubleshooter asked for, such as a search."""
    assert context.user_data is not None
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

    elif state == "troubleshooter:feedback":
        await feedback.handle_text(update, context, text)

    elif admin and state.startswith("troubleshooter:menu_"):
        await admin_content.handle_text(update, context, text)

    elif admin and state == "troubleshooter:user_search":
        await admin_users.handle_user_search(update, context, text)

    elif state == "troubleshooter:broadcast":
        await admin_broadcast.handle_broadcast(update, context, text)
        return
