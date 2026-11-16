from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.settings import SETTINGS


async def button_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    io_data = context.bot_data.get("io_boards", {})
    data = query.data
    board_name = data.split(":")[-1]
    if board_name not in io_data:
        await query.edit_message_text(
            f"❌ IO Board `{board_name}` not found.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 Back", callback_data="troubleshooter:ioboard"
                        )
                    ]
                ]
            ),
        )
        return

    board_entries = io_data[board_name]
    sections = {}
    for entry in board_entries:
        section = entry.get("section", "General")
        if section not in sections:
            sections[section] = []
        sections[section].append(entry)

    board = SETTINGS.content.IO_BOARDS.get(
        board_name, {"name": board_name.upper(), "can": ""}
    )
    response = f"📋 *{board['name']}*\n"
    if board["can"]:
        response += f"_{board['can']}_\n"
    response += "—" * 20 + "\n\n"

    for section, entries in sorted(sections.items()):
        response += f"🔹 *{section}*\n"
        for entry in entries:
            connector = entry.get("connector", "N/A")
            tdi_text = str(entry.get("tdi_text", "")).strip()

            if tdi_text and tdi_text.lower() != "nan":
                if len(tdi_text) > 50:
                    tdi_text = tdi_text[:47] + "..."
                response += f"`{connector}` | {tdi_text}\n"
            else:
                response += f"`{connector}`\n"
        response += "\n"

    if len(response) > 4096:
        response = response[:4080] + "\n\n*(truncated...)*"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="troubleshooter:ioboard")]]
    )

    await query.edit_message_text(
        response, parse_mode="Markdown", reply_markup=keyboard
    )


def board_menu():
    keyboard = []
    board_ids = sorted(SETTINGS.content.IO_BOARDS.keys())

    row = []
    for count, b_id in enumerate(board_ids, 1):
        label = SETTINGS.content.IO_BOARDS[b_id]["name"]
        row.append(
            InlineKeyboardButton(label, callback_data=f"troubleshooter:ioboard:{b_id}")
        )

        if count % 3 == 0:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [InlineKeyboardButton("🔙 Back ", callback_data="back:troubleshooter")]
    )

    return InlineKeyboardMarkup(keyboard)
