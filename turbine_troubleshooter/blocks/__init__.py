from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from .. import weather
from ..settings import SETTINGS
from ..tools import get_troubleshooter_content


async def handle_block(context: ContextTypes.DEFAULT_TYPE):
    code_count = len(context.bot_data.get("codes", {}))
    part_count = len(context.bot_data.get("parts", []))
    admin = context.user_data.get(
        "is_admin", not context.bot_data.get("is_troubleshooter")
    )

    text = f"🛠 *{SETTINGS.name} Bot*\n\nSelect a category:"

    content = get_troubleshooter_content()

    kb = []
    buttons = []

    for cb_data, item in content.items():
        if item.get("parent"):
            continue
        label = item["title"]
        buttons.append(InlineKeyboardButton(label, callback_data=cb_data))

    for i in range(0, len(buttons), 2):
        kb.append(buttons[i : i + 2])
    if weather.is_enabled() and context.bot_data.get("is_troubleshooter"):
        kb.append(
            [InlineKeyboardButton("🌦 Weather", callback_data="troubleshooter:weather")]
        )

    kb.append(
        [InlineKeyboardButton("🔢 WTG Info", callback_data="troubleshooter:wtg_search")]
    )

    kb.append(
        [
            InlineKeyboardButton(
                f"🔩 Search {part_count} Spare Parts",
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

    kb.append(
        [
            InlineKeyboardButton(
                "📝 Suggest Content", callback_data="troubleshooter:suggest"
            )
        ]
    )

    row = []
    if context.bot_data.get("is_troubleshooter"):
        row.append(
            InlineKeyboardButton(
                "👤 User Menu", callback_data="troubleshooter:user_menu"
            )
        )
    if admin:
        row.append(
            InlineKeyboardButton(
                "🔐 Admin Menu", callback_data="troubleshooter:admin_menu"
            )
        )
    if row:
        kb.append(row)

    kb.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
    return {
        "text": text,
        "reply_markup": InlineKeyboardMarkup(kb),
        "parse_mode": "Markdown",
    }
