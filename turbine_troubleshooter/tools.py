import asyncio
import difflib
import re
from datetime import timedelta

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter
from telegram.ext import ContextTypes

import turbine_troubleshooter
from turbine_troubleshooter.db import users_get
from turbine_troubleshooter.helpers import escape_markdown, is_local, is_owner
from turbine_troubleshooter.settings import SETTINGS, SKIPPED_WORDS


def find_wtg(text):
    prefix = SETTINGS.wtg_prefix.upper()
    match = re.fullmatch(
        rf"(?:{re.escape(prefix)})?([A-Z])(\d{{1,2}})", text.upper().replace(" ", "")
    )
    if not match:
        return None, None
    info = f"{prefix}{match.group(1)}{int(match.group(2)):02d}"
    return info, SETTINGS.content.WTG_MAP.get(info)


def get_troubleshooter_content():
    content = {"troubleshooter:ioboard": {"type": "menu", "title": "IO Boards"}}
    queue = [
        (None, title, data) for title, data in SETTINGS.content.MODULES_MAP.items()
    ]

    for parent, title, data in queue:
        key = f"{parent or 'troubleshooter'}:{re.sub(r'\W+', '_', title.lower()).strip('_')}"

        if isinstance(data, dict) and "menu" in data:
            content[key] = {
                "type": "menu",
                "title": title,
                "items": [],
                "parent": parent,
            }
            queue += [(key, t, d) for t, d in data["menu"].items()]
        else:
            if isinstance(data, dict):
                text = data["text"]
                if "photo" in data:
                    media_type, file_obj = "photo", data["photo"]
                elif "document" in data:
                    media_type, file_obj = "document", data["document"]
                else:
                    media_type, file_obj = "text", None
            else:
                text, media_type, file_obj = data, "text", None

            content[key] = {
                "type": media_type,
                "title": title,
                "content": text,
                "file": file_obj,
                "parent": parent,
            }

        if parent:
            content[parent]["items"].append(key)

    return dict(sorted(content.items(), key=lambda kv: kv[1]["title"].lower()))


def find_codes(query, codes, limit=5):
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


def find_parts(query, parts, limit=8):
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


async def set_user_roles(context: ContextTypes.DEFAULT_TYPE, user_id):
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


def alert_markup(enabled=True):
    toggle = "🔕 Turn Off Notifications" if enabled else "🔔 Turn On Notifications"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    toggle, callback_data="troubleshooter:notifications:alert"
                )
            ],
            [InlineKeyboardButton("❌ Close", callback_data="cancel")],
        ]
    )


async def send_notification_troubleshooter(
    user=None,
    action="new_user",
    code=None,
    advice=None,
    parts=None,
    message=None,
    target_id=None,
    audience="all",
):
    if turbine_troubleshooter.application is None:
        return 0, 0, []

    bot = turbine_troubleshooter.application.bot

    name = (
        escape_markdown(f"@{user.username}" if user.username else user.full_name)
        if user
        else None
    )
    close_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Close", callback_data="cancel")]]
    )
    user_markup = None

    match action:
        case "new_user":
            text = f"🚨 *New Troubleshooter Bot User*\n\n• {name}"
            parse_mode, reply_markup = "Markdown", close_markup
            to_alerts, to_users = True, False

        case "broadcast":
            title = (
                f"{SETTINGS.name} Admin Update"
                if audience == "admins"
                else f"{SETTINGS.name} Update"
            )
            text = f"📢 *{title}*\n\n{escape_markdown(message)}"
            parse_mode, reply_markup = "Markdown", close_markup
            to_alerts, to_users = False, True

        case "admin_revoked":
            text = f"🛡️ *{SETTINGS.name} Update*\n\nYour admin access has been removed."
            parse_mode, reply_markup = "Markdown", close_markup
            to_alerts, to_users = False, False

        case "access_revoked":
            text = f"🔒 *{SETTINGS.name} Update*\n\nYour access to the bot has been removed."
            parse_mode, reply_markup = "Markdown", close_markup
            to_alerts, to_users = False, False

        case (
            "code_added"
            | "code_edited"
            | "code_deleted"
            | "part_added"
            | "part_edited"
            | "part_deleted"
        ):
            kind, verb = action.split("_")

            if kind == "code":
                text = f"📝 *Troubleshooter Code {verb.capitalize()}*\n\n• Code: {escape_markdown(code)}\n\n"
                if advice:
                    text += f"• Advice:\n{escape_markdown(advice)}\n\n"
                if parts:
                    text += f"• Parts:\n{escape_markdown(parts)}\n\n"
            else:
                text = f"🔩 *Spare Part {verb.capitalize()}*\n\n• Part: `{code}`\n"
                if advice:
                    text += f"• Description: {escape_markdown(advice)}\n"
                if message:
                    text += f"• Change: {escape_markdown(message)}\n"
                text += "\n"

            text += f"• By: {name}"
            parse_mode, reply_markup = "Markdown", close_markup
            user_markup = alert_markup()
            to_alerts, to_users = True, True

            if not int(SETTINGS.notify_settings.get(f"notify_{verb}", 1)):
                audience = "admins"

        case _:
            raise ValueError(f"Unknown notification action: {action}")

    if to_alerts:
        await bot.send_message(
            chat_id=SETTINGS.alerts_chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    if target_id:
        try:
            await bot.send_message(
                chat_id=target_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Forbidden:
            pass

    if not to_users:
        return 0, 0, []

    try:
        records = await users_get()
    except Exception as e:
        print(f"❌ [DB] Failed to fetch users for broadcast: {e}")
        sentry_sdk.capture_exception(e)
        return 0, 0, []

    records = [r for r in records if r.get("is_approved") or r.get("is_admin")]

    if is_local():
        records = [r for r in records if is_owner(r["user_id"])]

    if audience == "admins":
        records = [r for r in records if r.get("is_admin")]
    elif isinstance(audience, int):
        records = [r for r in records if int(r["user_id"]) == audience]

    if action != "broadcast":
        records = [r for r in records if r.get("notifications_enabled", 1)]

    skip_user_id = (
        user.id if user and action != "broadcast" and not is_local() else None
    )
    success_count = 0
    blocked_count = 0
    successful_users = []

    for record in records:
        user_id = int(record["user_id"])
        if user_id == skip_user_id:
            continue

        raw = record.get("username")
        display_name = f"@{escape_markdown(raw)}" if raw else str(user_id)

        for _ in range(2):
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=user_markup or reply_markup,
                )
                success_count += 1
                successful_users.append(display_name)
                break
            except RetryAfter as e:
                wait = e.retry_after
                await asyncio.sleep(
                    wait.total_seconds() if isinstance(wait, timedelta) else wait
                )
            except Forbidden:
                blocked_count += 1
                break
            except Exception as e:
                print(f"⚠️ [Broadcast] {user_id}: {e}")
                sentry_sdk.capture_exception(e)
                break

        await asyncio.sleep(0.03)

    return success_count, blocked_count, successful_users
