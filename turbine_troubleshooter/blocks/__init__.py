from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from .. import weather
from ..helpers import get_troubleshooter_content
from ..settings import SETTINGS


async def handle_block(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """The troubleshooter's main menu as a block: {"text": ..., "reply_markup": ...}."""
    code_count = len(context.bot_data.get("codes", {}))
    part_count = len(context.bot_data.get("parts", []))
    is_troubleshooter = context.bot_data.get("is_troubleshooter")
    admin = context.user_data.get("is_admin", not is_troubleshooter)

    text = f"🛠 *{SETTINGS.name} Bot*\n\nSelect a category:"

    content = get_troubleshooter_content()

    kb = []
    buttons = []

    for cb_data, item in content.items():
        if item.get("parent") or cb_data == "troubleshooter:ioboard":
            continue
        label = item["title"]
        buttons.append(InlineKeyboardButton(label, callback_data=cb_data))

    for i in range(0, len(buttons), 2):
        kb.append(buttons[i : i + 2])
    if weather.is_enabled() and is_troubleshooter:
        kb.append(
            [InlineKeyboardButton("🌦 Weather", callback_data="troubleshooter:weather")]
        )

    if "troubleshooter:ioboard" in content:
        kb.append(
            [
                InlineKeyboardButton(
                    "🔌 IO Boards", callback_data="troubleshooter:ioboard"
                )
            ]
        )

    wtg_count = len(getattr(SETTINGS.content, "WTG_MAP", None) or {})
    if wtg_count:
        kb.append(
            [
                InlineKeyboardButton(
                    f"🔍 Search {wtg_count} WTG Serials",
                    callback_data="troubleshooter:wtg_search",
                )
            ]
        )

    kb.append(
        [
            InlineKeyboardButton(
                f"🔍 Search {part_count} Spare Parts",
                callback_data="troubleshooter:parts_search",
            )
        ]
    )

    kb.append(
        [
            InlineKeyboardButton(
                f"🔍 Search {code_count} Codes",
                callback_data="troubleshooter:code_search",
            )
        ]
    )

    admin_panel = InlineKeyboardButton(
        "⚙️ Admin Panel", callback_data="troubleshooter:admin_menu"
    )
    if is_troubleshooter:
        kb.append(
            [
                InlineKeyboardButton(
                    "💬 Feedback", callback_data="troubleshooter:feedback"
                ),
                InlineKeyboardButton(
                    "👤 User Menu", callback_data="troubleshooter:user_menu"
                ),
            ]
        )
    if admin:
        kb.append([admin_panel])

    kb.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
    return {
        "text": text,
        "reply_markup": InlineKeyboardMarkup(kb),
        "parse_mode": "Markdown",
    }
