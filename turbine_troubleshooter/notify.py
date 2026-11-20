"""Sending notifications to users, admins and the alerts chat."""

import asyncio
from datetime import timedelta
from typing import Any

import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter

import turbine_troubleshooter
from turbine_troubleshooter.db import users_get
from turbine_troubleshooter.helpers import escape_markdown, is_owner, is_test_mode
from turbine_troubleshooter.settings import NOTIFY_DEFAULTS, SETTINGS


def alert_markup(enabled: bool = True) -> InlineKeyboardMarkup:
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
    user: dict[str, Any] | None = None,
    action: str = "new_user",
    code: str | None = None,
    advice: str | None = None,
    parts: str | None = None,
    message: str | None = None,
    target_id: int | None = None,
    audience: str = "all",
    undo: Any = None,
    was: Any = None,
) -> tuple[int, int, list[int]]:
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

            if not int(
                SETTINGS.notify_settings.get(f"notify_{verb}", NOTIFY_DEFAULTS[verb])
            ):
                audience = "admins"

        case "menu_added" | "menu_edited" | "menu_deleted":
            verb = action.split("_")[1]
            text = f"📋 *Menu Item {verb.capitalize()}*\n\n• Item: {escape_markdown(code)}\n"
            if message:
                text += f"• Change: {escape_markdown(message)}\n"
            text += f"\n• By: {name}"
            parse_mode, reply_markup = "Markdown", close_markup
            user_markup = alert_markup()
            to_alerts = True
            to_users = verb == "added" or message == "File added"

            if not int(
                SETTINGS.notify_settings.get("notify_added", NOTIFY_DEFAULTS["added"])
            ):
                audience = "admins"

        case "feedback":
            text = f"💬 *Feedback*\n\n{escape_markdown(message)}\n\n• From: {name}"
            if user:
                text += f" (ID `{user.id}`)"
            parse_mode, reply_markup = "Markdown", close_markup
            to_alerts, to_users = True, False

        case _:
            raise ValueError(f"Unknown notification action: {action}")

    owner_text = (
        f"{text}\n\n• Was:\n{escape_markdown(was[:1500])}" if undo and was else text
    )
    owner_markup = (
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("↩️ Undo", callback_data=undo),
                    InlineKeyboardButton("❌ Close", callback_data="cancel"),
                ]
            ]
        )
        if undo
        else None
    )
    if to_alerts or undo:
        await bot.send_message(
            chat_id=SETTINGS.alerts_chat_id,
            text=owner_text,
            parse_mode=parse_mode,
            reply_markup=owner_markup or reply_markup,
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

    if is_test_mode():
        records = [r for r in records if is_owner(r["user_id"])]

    if audience == "admins":
        records = [r for r in records if r.get("is_admin")]
    elif isinstance(audience, int):
        records = [r for r in records if int(r["user_id"]) == audience]

    if action != "broadcast":
        records = [r for r in records if r.get("notifications_enabled", 1)]

    skip_user_id = (
        user.id if user and action != "broadcast" and not is_test_mode() else None
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
