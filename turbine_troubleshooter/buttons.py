"""Routes the troubleshooter's button presses to the right screen."""

import re
from pathlib import Path

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
)

from turbine_troubleshooter.helpers import (
    close_message,
    error_kb,
)

from . import weather
from .blocks import admin as admin_menu
from .blocks import codes, feedback, handle_block, io_boards, parts, user, wtg
from .blocks.admin import broadcast as admin_broadcast
from .blocks.admin import changes as admin_changes
from .blocks.admin import codes as admin_codes
from .blocks.admin import content as admin_content
from .blocks.admin import imports as admin_imports
from .blocks.admin import parts as admin_parts
from .blocks.admin import users as admin_users
from .helpers import get_troubleshooter_content


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a troubleshooter button press. A host routes "troubleshooter:"
    callbacks here."""
    query = update.callback_query
    data = query.data

    if data == "cancel":
        context.user_data["state"] = None
        await query.answer()
        await close_message(query, reopen="troubleshooter:home")
        return

    elif data == "troubleshooter:home":
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
            elif item.get("items") is not None:
                buttons = [
                    InlineKeyboardButton(content[k]["title"], callback_data=k)
                    for k in item["items"]
                ]
                kb = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
                kb.append(
                    [
                        InlineKeyboardButton(
                            "🔙 Back",
                            callback_data=item.get("parent") or "troubleshooter:home",
                        )
                    ]
                )
                text = f"*{item['title']}*\n\n" + (
                    "Select an option:" if buttons else "Nothing here yet."
                )
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

        links = []
        content_body = re.sub(
            r"(?m)(^[ \t]*)?\[([^\]\n]+)\]\((https?://[^)\s]+)\)([ \t]*(?:\n|\Z))?",
            lambda m: (
                f"{m[1] or ''}{m[2]}: {m[3]}{m[4] or ''}"
                if "@" in m[3].split("/")[2]
                else links.append((m[2], m[3]))
                or (
                    ""
                    if None not in (m[1], m[4])
                    else f"{m[1] or ''}{m[2]}{m[4] or ''}"
                )
            ),
            item.get("content", ""),
        ).strip()
        caption = f"*{item['title']}*\n\n{content_body}"
        back = [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data=item.get("parent") or "troubleshooter:home",
            )
        ]
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"🔗 {name}", url=url)] for name, url in links]
            + [back]
        )

        files = item.get("file")
        saved = files = files if isinstance(files, list) else [files]
        if context.bot_data.get("is_troubleshooter") and item.get("file_ids"):
            files = [fid or f for f, fid in zip(files, item["file_ids"])]
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
            try:
                await query.edit_message_text(
                    caption, parse_mode="Markdown", reply_markup=kb
                )
            except BadRequest:
                if not links:
                    raise
                await query.edit_message_text(
                    caption.rstrip() + "\n" + "".join(f"\n{n}: {u}" for n, u in links),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([back]),
                )
            return

        await close_message(query)
        kind = "photo" if item["type"] == "photo" else "document"
        attempts = (
            [files, saved]
            if files != saved
            and all(isinstance(f, Path) and f.is_file() for f in saved)
            else [files]
        )
        for attempt in attempts:
            try:
                for i, f in enumerate(attempt):
                    await getattr(query.message, f"reply_{kind}")(
                        **{kind: f},
                        caption=caption if i == len(attempt) - 1 else None,
                        parse_mode="Markdown",
                        reply_markup=kb if i == len(attempt) - 1 else error_kb(None),
                    )
                break
            except BadRequest:
                if attempt is attempts[-1]:
                    raise
                sentry_sdk.capture_message(
                    "Troubleshooter file id rejected; sent the saved file",
                    level="warning",
                )
        return

    elif data.startswith("troubleshooter:ioboard:"):
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

    elif data == "troubleshooter:feedback":
        await feedback.button_feedback(update, context)

    elif admin and data == "troubleshooter:part_add":
        await admin_parts.button_part_add(update, context)

    elif data in ("troubleshooter:user_menu", "troubleshooter:notifications:toggle"):
        await user.button_menu(update, context)

    elif data == "troubleshooter:admin:request":
        await user.button_request_admin(update, context)

    elif data == "troubleshooter:access_request":
        await user.button_request_access(update, context)

    elif data.startswith("troubleshooter:access:approve:"):
        await admin_users.button_access_approve(update, context)

    elif data.startswith("troubleshooter:access:deny:"):
        await admin_users.button_access_deny(update, context)

    elif data.startswith("troubleshooter:admin:approve:"):
        await admin_users.button_admin_approve(update, context)

    elif data.startswith("troubleshooter:admin:deny:"):
        await admin_users.button_admin_deny(update, context)

    elif data == "troubleshooter:notifications:alert":
        await user.button_alert_toggle(update, context)

    elif data.startswith("troubleshooter:delreq"):
        await admin_changes.button_delete_requests(update, context)

    elif data.startswith("troubleshooter:announce:"):
        await admin_broadcast.button_announce(update, context)

    elif data.startswith("troubleshooter:undo:"):
        await admin_changes.button_undo(update, context)

    elif data.startswith("troubleshooter:import"):
        await admin_imports.handle_button(update, context)

    elif admin and data.startswith("troubleshooter:menu_"):
        await admin_content.handle_button(update, context)

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
        await admin_changes.button_pending(update, context)

    elif admin and data == "troubleshooter:user_search":
        await admin_users.button_user_search(update, context)

    elif admin and data == "troubleshooter:export_menu":
        await admin_menu.button_export_menu(update, context)

    elif admin and data.startswith("troubleshooter:export:"):
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

    else:
        await query.answer(
            "This button is out of date. Send /start for the latest menu.",
            show_alert=True,
        )
