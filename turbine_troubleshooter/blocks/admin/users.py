import html
from collections import Counter
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import (
    admin_add,
    admin_remove,
    request_remove,
    user_approve,
    user_get,
    user_revoke,
    users_get,
)
from turbine_troubleshooter.helpers import error_kb, escape_markdown, is_owner, own_bot
from turbine_troubleshooter.settings import SETTINGS

from ...helpers import user_is_admin
from ...notify import send_notification_troubleshooter

PAGE_SIZE = 10
SORTS = ("name", "added", "edits", "login")
BADGES = {"owner": "👑", "admin": "🛡️", "approved": "✅", "locked": "🔒"}
ROLE_LABELS = {
    "owner": "Owner",
    "admin": "Admin",
    "approved": "Approved user",
    "locked": "No access",
}
ACTIONS = {
    "access_add": ("✅ Give access", "Give {name} access to the bot?"),
    "admin_add": (
        "🛡️ Make admin",
        "Make {name} an admin? They'll be able to add, edit and delete "
        "codes and parts.",
    ),
    "admin_remove": (
        "⬇️ Remove admin",
        "Remove {name}'s admin rights? They keep normal access.",
    ),
    "access_remove": (
        "🚫 Remove access",
        "Remove {name}'s access? They'll be locked out of the bot.",
    ),
}
UNAUTHORIZED = "⚠️ Unauthorized: Admin access required."
OWNER_ONLY = "⚠️ Only the owner can do that."
BACK_TO_PANEL = InlineKeyboardButton(
    "🔙 Back", callback_data="troubleshooter:admin_menu"
)


def role(user, context):
    uid = int(user["user_id"])
    if is_owner(uid):
        return "owner"
    if uid in context.bot_data.get("troubleshooter_admins", {}):
        return "admin"
    if uid in context.bot_data.get("troubleshooter_approved", set()):
        return "approved"
    return "locked"


def display_name(user):
    name = user["username"]
    if name and " " not in name:
        name = f"@{name}"
    return name


def pending_requests(context):
    return [
        (uid, name, kind)
        for kind in ("access", "admin")
        for uid, name in context.bot_data.get(f"pending_{kind}_requests", {}).items()
    ]


def contributions(context):
    items = [
        *context.bot_data.get("codes", {}).values(),
        *context.bot_data.get("parts", []),
    ]
    added = Counter(i["added_by"] for i in items if i.get("added_by"))
    edited = Counter(e["by"] for i in items for e in (i.get("edits") or []))
    return added, edited


async def edit(query, text, kb):
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


async def tell_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id,
    text,
    reply_markup=None,
    parse_mode=None,
):
    try:
        await own_bot(context).send_message(
            user_id,
            text,
            reply_markup=reply_markup or error_kb(None),
            parse_mode=parse_mode,
        )
    except Exception:
        pass


def clear_request(context, user_id):
    for kind in ("access", "admin"):
        context.bot_data.get(f"pending_{kind}_requests", {}).pop(user_id, None)


async def grant_access(context: ContextTypes.DEFAULT_TYPE, user_id):
    await user_approve(user_id)
    context.bot_data.setdefault("troubleshooter_approved", set()).add(user_id)
    clear_request(context, user_id)
    await request_remove(user_id)
    await tell_user(
        context,
        user_id,
        f"✅ *You're in!* You now have access to the "
        f"{escape_markdown(SETTINGS.name)} Bot.\n\n"
        "• Search fault codes and spare parts\n"
        "• Browse the menus for guides, photos and PDFs\n"
        "• Tap 💬 Feedback if something's missing or wrong\n\n"
        "You'll get a message when something new is added. Turn that off any "
        "time from 👤 User Menu.",
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🛠 Open", callback_data="troubleshooter:home"),
                    InlineKeyboardButton("❌ Close", callback_data="cancel"),
                ]
            ]
        ),
        parse_mode="Markdown",
    )


async def grant_admin(context: ContextTypes.DEFAULT_TYPE, user_id, name):
    await admin_add(user_id, name.lstrip("@"))
    context.bot_data.setdefault("troubleshooter_admins", {})[user_id] = name
    clear_request(context, user_id)
    await request_remove(user_id)
    await tell_user(
        context,
        user_id,
        f"🛡️ *You're now an admin* of the {escape_markdown(SETTINGS.name)} Bot.\n\n"
        "You can add and edit fault codes, spare parts and menu pages, including "
        "photos and PDFs. Changes go live straight away. Deletes need the "
        "owner's OK first.",
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⚙️ Admin Panel", callback_data="troubleshooter:admin_menu"
                    )
                ],
                [InlineKeyboardButton("❌ Close", callback_data="cancel")],
            ]
        ),
        parse_mode="Markdown",
    )


async def remove_admin(context: ContextTypes.DEFAULT_TYPE, user_id):
    removed = await admin_remove(user_id)
    await user_approve(user_id)
    context.bot_data.get("troubleshooter_admins", {}).pop(user_id, None)
    context.bot_data.setdefault("troubleshooter_approved", set()).add(user_id)
    if removed:
        await send_notification_troubleshooter(
            action="admin_revoked", target_id=user_id
        )


async def remove_access(context: ContextTypes.DEFAULT_TYPE, user_id):
    await admin_remove(user_id)
    removed = await user_revoke(user_id)
    context.bot_data.get("troubleshooter_admins", {}).pop(user_id, None)
    context.bot_data.get("troubleshooter_approved", set()).discard(user_id)
    if removed:
        await send_notification_troubleshooter(
            action="access_revoked", target_id=user_id
        )


async def deny_request(context: ContextTypes.DEFAULT_TYPE, user_id, kind):
    name = context.bot_data.get(f"pending_{kind}_requests", {}).pop(user_id, None)
    await request_remove(user_id)
    what = "admin request" if kind == "admin" else "access request"
    await tell_user(
        context, user_id, f"❌ Your {SETTINGS.name} Bot {what} was declined."
    )
    return name


def request_target(query):
    parts = query.data.split(":")
    return int(parts[3]), parts[-1] == "p"


async def lookup_name(context: ContextTypes.DEFAULT_TYPE, user_id):
    try:
        chat = await context.bot.get_chat(user_id)
    except Exception:
        return str(user_id)
    if chat.username:
        return f"@{chat.username}"
    return chat.first_name or str(user_id)


DECISIONS = {
    ("admin", "approve"): "✅ Approved {name} as an admin.",
    ("admin", "deny"): "❌ Denied admin for {name}.",
    ("access", "approve"): "✅ Gave {name} access.",
    ("access", "deny"): "❌ Denied access for {name}.",
}


async def button_decide_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        return
    _, kind, verdict = query.data.split(":")[:3]
    target_id, from_panel = request_target(query)
    name = context.bot_data.get(f"pending_{kind}_requests", {}).get(target_id)

    if verdict == "deny":
        await deny_request(context, target_id, kind)
    elif kind == "admin":
        name = name or await lookup_name(context, target_id)
        await grant_admin(context, target_id, name)
    else:
        await grant_access(context, target_id)

    message = DECISIONS[kind, verdict]
    if from_panel:
        status = message.format(name=html.escape(str(name or target_id)))
        from .changes import show_pending

        await show_pending(query, context, status=status)
        return
    await query.edit_message_text(
        message.format(name=escape_markdown(str(name or target_id))),
        parse_mode="Markdown",
        reply_markup=error_kb(None),
    )


button_admin_approve = button_admin_deny = button_decide_request
button_access_approve = button_access_deny = button_decide_request


def page_count(total):
    return max((total - 1) // PAGE_SIZE + 1, 1)


def nav_row(callback_prefix, page, pages):
    row = []
    if page > 0:
        row.append(
            InlineKeyboardButton("◀️ Prev", callback_data=f"{callback_prefix}{page - 1}")
        )
    if page < pages - 1:
        row.append(
            InlineKeyboardButton("Next ▶️", callback_data=f"{callback_prefix}{page + 1}")
        )
    return [row] if row else []


def users_back(context):
    sort_by, page = context.user_data.get("user_list", ("name", 0))
    return f"troubleshooter:user_list:{sort_by}:{page}"


def matches(user, search):
    search = search.lower().lstrip("@")
    return search in (user["username"] or "").lower() or search == str(user["user_id"])


async def button_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not user_is_admin(context):
        await query.answer(UNAUTHORIZED, show_alert=True)
        return

    parts = query.data.split(":")
    if len(parts) == 2:
        context.user_data.pop("user_search", None)
    sort_by = parts[2] if len(parts) > 2 and parts[2] in SORTS else "name"
    try:
        page = max(int(parts[3]), 0) if len(parts) > 3 else 0
    except ValueError:
        page = 0

    text, kb = await users_list(context, query.from_user.id, sort_by, page)
    await edit(query, text, kb)


async def button_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not user_is_admin(context):
        await query.answer(UNAUTHORIZED, show_alert=True)
        return
    context.user_data["state"] = "troubleshooter:user_search"
    context.user_data["last_msg_id"] = query.message.message_id
    await edit(
        query,
        "🔍 <b>Find a User</b>\n\nType part of a username, or a Telegram ID:",
        [[InlineKeyboardButton("🔙 Cancel", callback_data=users_back(context))]],
    )


async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    context.user_data["state"] = None
    if not user_is_admin(context):
        return
    context.user_data["user_search"] = text[:64]
    sort_by, _ = context.user_data.get("user_list", ("name", 0))
    body, kb = await users_list(context, update.effective_user.id, sort_by, 0)
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get("last_msg_id"),
            text=body,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def users_list(context: ContextTypes.DEFAULT_TYPE, viewer_id, sort_by, page):
    users = await users_get()
    total = len(users)
    search = context.user_data.get("user_search")
    if search:
        users = [u for u in users if matches(u, search)]
    added, edited = contributions(context)

    if sort_by == "added":
        users.sort(key=lambda u: added.get(display_name(u), 0), reverse=True)
    elif sort_by == "edits":
        users.sort(key=lambda u: edited.get(display_name(u), 0), reverse=True)
    elif sort_by == "login":
        users.sort(key=lambda u: u.get("last_login") or datetime.min, reverse=True)
    else:
        users.sort(key=lambda u: (display_name(u) or "").lower())

    pages = page_count(len(users))
    page = min(page, pages - 1)
    context.user_data["user_list"] = (sort_by, page)

    counts = Counter(role(u, context) for u in users)
    text = f"👥 <b>Users</b> ({total})\n\n"
    if search:
        text += f"🔍 Matching “{html.escape(search)}”: {len(users)}\n\n"
    if not users:
        text += "No matching users." if search else "No users registered yet."
    else:
        text += " · ".join(
            f"{BADGES[r]} {counts[r]} {ROLE_LABELS[r].lower()}"
            for r in ("admin", "approved", "locked")
            if counts[r]
        )
        text += "\n\nTap a user to see details."
        if pages > 1:
            text += f"\n\nPage {page + 1} of {pages}"

    kb = []
    for u in users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        name = display_name(u) or f"ID {u['user_id']}"
        n_added, n_edited = added.get(name, 0), edited.get(name, 0)
        stats = f" · ➕{n_added} ✏️{n_edited}" if (n_added or n_edited) else ""
        kb.append(
            [
                InlineKeyboardButton(
                    f"{BADGES[role(u, context)]} {name}{stats}",
                    callback_data=f"troubleshooter:user:{u['user_id']}",
                )
            ]
        )

    kb += nav_row(f"troubleshooter:user_list:{sort_by}:", page, pages)

    def sort_button(key, label):
        return InlineKeyboardButton(
            f"• {label} •" if key == sort_by else label,
            callback_data=f"troubleshooter:user_list:{key}:0",
        )

    kb.append([sort_button("name", "🔤 Name"), sort_button("added", "➕ Added")])
    kb.append([sort_button("edits", "✏️ Edits"), sort_button("login", "🕒 Login")])
    kb.append(
        [InlineKeyboardButton("🔍 Search", callback_data="troubleshooter:user_search")]
        + (
            [
                InlineKeyboardButton(
                    "✖️ Clear search", callback_data="troubleshooter:user_list"
                )
            ]
            if search
            else []
        )
    )

    requests = pending_requests(context)
    if is_owner(viewer_id) and requests:
        kb.append(
            [
                InlineKeyboardButton(
                    f"⏳ Pending requests ({len(requests)})",
                    callback_data="troubleshooter:pending",
                )
            ]
        )
    kb.append([BACK_TO_PANEL])
    return text, kb


def available_actions(user_role):
    return {
        "locked": ["access_add"],
        "approved": ["admin_add", "access_remove"],
        "admin": ["admin_remove", "access_remove"],
    }.get(user_role, [])


async def find_user(user_id):
    return await user_get(user_id)


async def show_card(query, context, user_id, status=None):
    user = await find_user(user_id)
    if user is None:
        await edit(
            query,
            "That user isn't registered any more.",
            [[InlineKeyboardButton("🔙 Users", callback_data=users_back(context))]],
        )
        return

    user_role = role(user, context)
    name = display_name(user)
    label = html.escape(name) if name else f"ID {user_id}"
    username = user["username"]
    href = (
        f"https://t.me/{username}"
        if username and " " not in username
        else f"tg://user?id={user_id}"
    )
    added, edited = contributions(context)

    lines = [
        f'{BADGES[user_role]} <a href="{href}">{label}</a>',
        "",
        f"Role: {ROLE_LABELS[user_role]}",
        f"ID: <code>{user_id}</code>",
        "Last login: "
        + (f"{user['last_login']:%d %b %Y}" if user.get("last_login") else "never"),
        f"Added: {added.get(name, 0)} · Edits: {edited.get(name, 0)}",
    ]
    for uid, _, kind in pending_requests(context):
        if uid == user_id:
            lines.append(f"⏳ Has asked for {'admin' if kind == 'admin' else 'access'}")
    text = (f"{status}\n\n" if status else "") + "\n".join(lines)

    kb = []
    if is_owner(query.from_user.id):
        kb = [
            [
                InlineKeyboardButton(
                    ACTIONS[action][0],
                    callback_data=f"troubleshooter:user_act:{action}:{user_id}",
                )
            ]
            for action in available_actions(user_role)
        ]
    kb.append([InlineKeyboardButton("🔙 Users", callback_data=users_back(context))])
    await edit(query, text, kb)


async def button_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not user_is_admin(context):
        await query.answer(UNAUTHORIZED, show_alert=True)
        return
    await show_card(query, context, int(query.data.split(":")[2]))


def parse_action(query):
    _, _, action, user_id = query.data.split(":")
    return action, int(user_id)


async def button_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer(OWNER_ONLY, show_alert=True)
        return
    action, user_id = parse_action(query)
    user = await find_user(user_id)
    if action not in ACTIONS or user is None:
        await show_card(query, context, user_id)
        return
    if action not in available_actions(role(user, context)):
        await show_card(query, context, user_id, status="ℹ️ Nothing to change.")
        return

    name = html.escape(display_name(user) or f"ID {user_id}")
    label, question = ACTIONS[action]
    await edit(
        query,
        question.format(name=f"<b>{name}</b>"),
        [
            [
                InlineKeyboardButton(
                    f"Yes, {label.split(' ', 1)[1].lower()}",
                    callback_data=f"troubleshooter:user_do:{action}:{user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Cancel", callback_data=f"troubleshooter:user:{user_id}"
                )
            ],
        ],
    )


async def button_user_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer(OWNER_ONLY, show_alert=True)
        return
    action, user_id = parse_action(query)
    user = await find_user(user_id)
    if user is None or action not in available_actions(role(user, context)):
        await show_card(query, context, user_id, status="ℹ️ Nothing to change.")
        return

    name = display_name(user) or str(user_id)
    if action == "access_add":
        await grant_access(context, user_id)
        status = "✅ Access given."
    elif action == "admin_add":
        await grant_admin(context, user_id, name)
        status = "✅ Now an admin."
    elif action == "admin_remove":
        await remove_admin(context, user_id)
        status = "✅ Admin rights removed."
    else:
        await remove_access(context, user_id)
        status = "✅ Access removed."

    await show_card(query, context, user_id, status=status)
