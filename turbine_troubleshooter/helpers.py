"""Shared helpers: owner checks, error handling, searches and the menu content."""

import difflib
import re
import traceback
from pathlib import Path
from typing import Any

import sentry_sdk
from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import turbine_troubleshooter
from turbine_troubleshooter.settings import SETTINGS, SKIPPED_WORDS

ERROR_REPLY = "⚠️ Something went wrong. It's been logged."


def is_test_mode() -> bool:
    return str(SETTINGS.test_mode).lower() in ("1", "true", "yes", "on")


def is_owner(user_id: Any) -> bool:
    chat_id = SETTINGS.owner_id
    if not chat_id:
        return False
    try:
        return int(user_id) == int(chat_id)
    except (TypeError, ValueError):
        return False


def own_bot(context: ContextTypes.DEFAULT_TYPE) -> Bot:
    if (
        context.bot_data.get("is_troubleshooter")
        or turbine_troubleshooter.application is None
    ):
        return context.bot
    return turbine_troubleshooter.application.bot


def escape_markdown(text: str) -> str:
    escape_chars = r"_*[`"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))


def error_kb(block: dict[str, Any] = None) -> InlineKeyboardMarkup:
    text = f"🔙 Back to {block.capitalize()}" if block else "❌ Close"
    callback = f"back:{block}" if block else "cancel"
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=callback)]])


async def close_message(
    query: CallbackQuery, title: str | None = None, reopen: str = "troubleshooter:home"
) -> None:
    title = title or f"🛠 *{SETTINGS.name} Bot*"
    try:
        await query.message.delete()
    except BadRequest:
        edit = (
            query.edit_message_text
            if query.message.text
            else query.edit_message_caption
        )
        markup = (
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Open Menu", callback_data=reopen)]]
            )
            if reopen
            else None
        )
        try:
            await edit(title, parse_mode="Markdown", reply_markup=markup)
        except BadRequest:
            pass


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if any(noise.lower() in str(error).lower() for noise in SETTINGS.noise_filters):
        return

    if isinstance(update, Update):
        if update.edited_message:
            return
        if update.effective_message:
            try:
                await update.effective_message.reply_text(
                    ERROR_REPLY, reply_markup=error_kb()
                )
            except Exception:
                pass

    sentry_sdk.capture_exception(error)
    if is_test_mode():
        traceback.print_exception(error)


def error_handler_noise_filter(record: Any) -> bool:
    msg = record.getMessage()
    return not any(n in msg for n in SETTINGS.noise_filters)


def find_wtg(text: str) -> tuple[str | None, dict[str, Any] | None]:
    prefix = SETTINGS.wtg_prefix.upper()
    match = re.fullmatch(
        rf"(?:{re.escape(prefix)})?([A-Z])(\d{{1,2}})", text.upper().replace(" ", "")
    )
    if not match:
        return None, None
    info = f"{prefix}{match.group(1)}{int(match.group(2)):02d}"
    return info, SETTINGS.content.WTG_MAP.get(info)


def get_troubleshooter_content() -> dict[str, dict[str, Any]]:
    content = (
        {"troubleshooter:ioboard": {"type": "menu", "title": "IO Boards"}}
        if getattr(SETTINGS.content, "IO_BOARDS", None)
        else {}
    )

    menu = SETTINGS.menu or {"nodes": [], "attachments": []}
    attached = {}
    for a in menu["attachments"]:
        attached.setdefault(a["node_id"], []).append(a)

    for n in sorted(menu["nodes"], key=lambda n: (n["sort_order"], n["id"])):
        parent = n["parent_id"] and f"troubleshooter:menu:{n['parent_id']}"
        if n["type"] == "submenu":
            item = {
                "type": "menu",
                "title": n["title"],
                "items": [],
                "parent": parent,
            }
        else:
            files = attached.get(n["id"], [])
            paths = [Path(SETTINGS.files_dir) / a["path"] for a in files]
            item = {
                "type": files[0]["type"] if files else "text",
                "title": n["title"],
                "content": n["body"] or "",
                "file": (paths[0] if len(paths) == 1 else paths) or None,
                "file_ids": [a.get("file_id") for a in files],
                "parent": parent,
            }
        content[f"troubleshooter:menu:{n['id']}"] = item

    for key, item in list(content.items()):
        if item.get("parent") in content:
            content[item["parent"]]["items"].append(key)

    return dict(sorted(content.items(), key=lambda kv: kv[1]["title"].lower()))


def find_codes(
    query: CallbackQuery, codes: dict[str, dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []

    scored = []
    for c in codes.values():
        cl = str(c["code"]).lower()
        if cl == q:
            continue
        if cl.startswith(q):
            score = 300 - (len(cl) - len(q))
        elif q in cl:
            score = 200 - abs(len(cl) - len(q))
        else:
            ratio = difflib.SequenceMatcher(None, q, cl).ratio()
            if ratio < 0.6:
                continue
            score = ratio * 100
        scored.append((score, c))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in scored[:limit]]


def find_parts(
    query: CallbackQuery, parts: list[dict[str, Any]], limit: int = 8
) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []
    words = re.findall(r"\w+", q)

    scored = []
    for p in parts:
        part_no = p["part_no"].lower()
        desc = p["description"].lower()
        hay = f"{desc} {p['section'].lower()}"
        if q == part_no:
            return [p]
        if part_no.startswith(q):
            scored.append((500, p))
            continue
        hits = sum(w in hay for w in words)
        if hits == len(words):
            score = 300 + sum(w in desc for w in words) * 40 - len(desc) / 10
            score -= 50 * sum(a in desc and a not in q for a in SKIPPED_WORDS)
        elif hits:
            score = 100 * hits / len(words) + sum(w in desc for w in words) * 10
        else:
            ratio = difflib.SequenceMatcher(None, q, desc).ratio()
            if ratio < 0.6:
                continue
            score = ratio * 100
        scored.append((score, p))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in scored[:limit]]


async def set_user_roles(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    assert context.user_data is not None
    uid = int(user_id)
    is_admin = is_owner(uid) or uid in context.bot_data.get("troubleshooter_admins", {})
    context.user_data["is_admin"] = is_admin
    context.user_data["is_approved"] = is_admin or uid in context.bot_data.get(
        "troubleshooter_approved", set()
    )


def user_is_admin(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )
