import html
from collections import Counter
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from troubleshooter.db import (
    admin_add,
    admin_remove,
    user_approve,
    user_revoke,
    users_get,
)
from troubleshooter.helpers import error_kb, escape_markdown, is_owner
from troubleshooter.settings import SETTINGS

from ...tools import send_notification_troubleshooter, user_is_admin


async def button_admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        return

    admins = context.bot_data.get("troubleshooter_admins", {})
    if not admins:
        text = "⚙️ *Admins*\n\nNo admins yet."
        kb = [
            [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
        ]
    else:
        text = "⚙️ *Admins*\n\nTap an admin to remove their access:"
        kb = [
            [
                InlineKeyboardButton(
                    f"🗑 {name or uid}",
                    callback_data=f"troubleshooter:admin_revoke:{uid}",
                )
            ]
            for uid, name in admins.items()
        ]
        kb.append(
            [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
        )

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


async def button_admin_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    target_id = int(query.data.split(":")[-1])
    removed = await admin_remove(target_id)
    context.bot_data.get("troubleshooter_admins", {}).pop(target_id, None)

    if removed:
        await send_notification_troubleshooter(
            action="admin_revoked", target_id=target_id
        )

    await button_admin_list(update, context)


async def button_admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not is_owner(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    target_id = int(data.split(":")[-1])

    name = context.bot_data.get("pending_admin_requests", {}).pop(target_id, None)

    if not name:
        try:
            chat_info = await context.bot.get_chat(target_id)
            if chat_info.username:
                name = f"@{chat_info.username}"
            elif chat_info.first_name:
                name = chat_info.first_name
            else:
                name = str(target_id)
        except Exception:
            name = str(target_id)

    await admin_add(target_id, name.lstrip("@"))
    context.bot_data.setdefault("troubleshooter_admins", {})[target_id] = name
    await query.edit_message_text(
        f"✅ Approved {escape_markdown(name)} as a troubleshooter admin.",
        parse_mode="Markdown",
        reply_markup=error_kb(None),
    )
    try:
        await context.bot.send_message(
            target_id,
            f"✅ You've been granted {SETTINGS.name} Bot admin access.\n\n"
            "You can now add, edit and remove fault codes and spare parts.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔐 Admin Menu",
                            callback_data="troubleshooter:admin_menu",
                        )
                    ],
                    [InlineKeyboardButton("❌ Close", callback_data="cancel")],
                ]
            ),
        )
    except Exception:
        pass


async def button_admin_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not is_owner(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    target_id = int(data.split(":")[-1])
    name = context.bot_data.get("pending_admin_requests", {}).pop(target_id, None)
    await query.edit_message_text(
        f"❌ Denied admin request from {escape_markdown(str(name or target_id))}.",
        parse_mode="Markdown",
        reply_markup=error_kb(None),
    )
    try:
        await context.bot.send_message(
            target_id,
            f"❌ Your {SETTINGS.name} Bot admin request was declined.",
            reply_markup=error_kb(None),
        )
    except Exception:
        pass


async def button_access_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        return
    target_id = int(query.data.split(":")[-1])
    name = context.bot_data.get("pending_access_requests", {}).pop(target_id, None)

    await user_approve(target_id)
    context.bot_data.setdefault("troubleshooter_approved", set()).add(target_id)
    await query.edit_message_text(
        f"✅ Gave {escape_markdown(str(name or target_id))} access to the troubleshooter.",
        parse_mode="Markdown",
        reply_markup=error_kb(None),
    )
    try:
        await context.bot.send_message(
            target_id,
            f"✅ You've been given access to the {SETTINGS.name} Bot.\n\n"
            "Send /start to open it.",
            reply_markup=error_kb(None),
        )
    except Exception:
        pass


async def button_access_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        return
    target_id = int(query.data.split(":")[-1])
    name = context.bot_data.get("pending_access_requests", {}).pop(target_id, None)

    await query.edit_message_text(
        f"❌ Denied troubleshooter access for {escape_markdown(str(name or target_id))}.",
        parse_mode="Markdown",
        reply_markup=error_kb(None),
    )
    try:
        await context.bot.send_message(
            target_id,
            f"❌ Your {SETTINGS.name} Bot access request was declined.",
            reply_markup=error_kb(None),
        )
    except Exception:
        pass


async def button_access_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, status=None
):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    approved = [u for u in await users_get() if u["is_approved"] and not u["is_admin"]]
    approved.sort(key=lambda u: (u["username"] or "").lower())

    text = f"{status}\n\n" if status else ""
    text += "🔑 *Approved Users*\n\n" + (
        "Tap a user to remove their access:" if approved else "No approved users."
    )
    kb = [
        [
            InlineKeyboardButton(
                f"🚫 {u['username'] or u['user_id']}",
                callback_data=f"troubleshooter:access_revoke:{u['user_id']}",
            )
        ]
        for u in approved
    ]
    kb.append(
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")]
    )

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


async def button_access_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    target_id = int(query.data.split(":")[-1])
    removed = await user_revoke(target_id)
    context.bot_data.get("troubleshooter_approved", set()).discard(target_id)

    if removed:
        await send_notification_troubleshooter(
            action="access_revoked", target_id=target_id
        )

    await button_access_list(update, context, status="✅ Access removed.")


async def button_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not user_is_admin(context):
        await query.answer("⚠️ Unauthorized: Admin access required.", show_alert=True)
        return

    parts = query.data.split(":")
    sort_by = parts[2] if len(parts) > 2 else "name"
    if sort_by not in ("added", "edits", "login"):
        sort_by = "name"

    users = await users_get()

    items = [
        *context.bot_data.get("codes", {}).values(),
        *context.bot_data.get("parts", []),
    ]
    added = Counter(i["added_by"] for i in items if i.get("added_by"))
    edited = Counter(e["by"] for i in items for e in (i.get("edits") or []))

    def display_name(u):
        raw_name = u["username"]
        if raw_name and " " not in raw_name:
            raw_name = f"@{raw_name}"
        return raw_name

    if sort_by == "added":
        users.sort(key=lambda u: added.get(display_name(u), 0), reverse=True)
    elif sort_by == "edits":
        users.sort(key=lambda u: edited.get(display_name(u), 0), reverse=True)
    elif sort_by == "login":
        users.sort(key=lambda u: u.get("last_login") or datetime.min, reverse=True)
    else:
        users.sort(key=lambda u: (display_name(u) or "").lower())

    if not users:
        text = "👥 <b>Registered Users</b>\n\nNo users registered yet."
    else:
        text = f"👥 <b>Registered Users</b> (Total: {len(users)})\n\n"
        for u in users:
            uid = u["user_id"]
            raw_name = display_name(u)

            label = html.escape(raw_name) if raw_name else f"ID {uid}"
            username = u["username"]
            if username and " " not in username:
                href = f"https://t.me/{username}"
            else:
                href = f"tg://user?id={uid}"
            name_str = f'<a href="{href}">{label}</a>'
            admin_badge = " 🛡️ " if u["is_admin"] == 1 else ""

            n_added = added.get(raw_name, 0)
            n_edited = edited.get(raw_name, 0)
            stats = f" — ➕ {n_added} · ✏️ {n_edited}" if (n_added or n_edited) else ""
            seen = f" · 🕒 {u['last_login']:%d %b}" if u.get("last_login") else ""

            text += f"• {name_str}{admin_badge}{stats}{seen}\n"

    def sort_button(key, label):
        return InlineKeyboardButton(
            f"• {label} •" if key == sort_by else label,
            callback_data=f"troubleshooter:user_list:{key}",
        )

    kb = [
        [sort_button("name", "🔤 Name"), sort_button("added", "➕ Added")],
        [sort_button("edits", "✏️ Edits"), sort_button("login", "🕒 Login")],
        [InlineKeyboardButton("📤 Export Users", callback_data="export:users")],
        [InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:admin_menu")],
    ]

    try:
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise
