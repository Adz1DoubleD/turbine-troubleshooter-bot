import csv
import io
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.db import io_boards_replace, wtgs_replace
from turbine_troubleshooter.helpers import escape_markdown, is_owner
from turbine_troubleshooter.settings import SETTINGS

MAX_IMPORT_BYTES = 1024 * 1024
KINDS = {
    "wtgs": ("🔢 Turbines", ["name", "serial", "ip"], [], "turbine"),
    "io_boards": (
        "📋 IO Boards",
        ["board", "board_name", "pin"],
        ["section", "can_node", "description"],
        "IO board pin",
    ),
}
TO_IMPORT = InlineKeyboardButton("🔙 Import", callback_data="troubleshooter:import")


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id) or not context.bot_data.get(
        "is_troubleshooter"
    ):
        await query.answer(
            "⚠️ Only the owner can import, in the troubleshooter bot.",
            show_alert=True,
        )
        return

    bits = query.data.split(":")
    context.user_data["last_msg_id"] = query.message.message_id

    if len(bits) == 2:
        context.user_data["state"] = None
        text = (
            "📥 *Import*\n\nReplace every turbine or every IO board pin from a CSV "
            "file. To start from what's there now, use 📤 Export, edit the file, "
            "and send it back here."
        )
        kb = [
            [
                InlineKeyboardButton(label, callback_data=f"troubleshooter:import:{k}")
                for k, (label, *_) in KINDS.items()
            ],
            [
                InlineKeyboardButton(
                    "🔙 Admin Panel", callback_data="troubleshooter:admin_menu"
                )
            ],
        ]

    elif bits[2] in KINDS:
        label, required, optional, thing = KINDS[bits[2]]
        context.user_data["state"] = f"troubleshooter:import:{bits[2]}"
        text = (
            f"📥 *{label}*\n\nSend a CSV file with these columns:\n"
            f"`{', '.join(required + optional)}`\n\n"
            f"It replaces every {thing}. You'll see what changes before anything "
            "is saved."
        )
        kb = [[TO_IMPORT]]

    elif bits[2] == "save" and context.user_data.get("import_draft"):
        draft = context.user_data.pop("import_draft")
        rows = draft["rows"]
        if draft["kind"] == "wtgs":
            await wtgs_replace(rows)
            SETTINGS.content.WTG_MAP = {
                r["wtg"]: {"serial": r["serial"], "ip": r["ip"]} for r in rows
            }
            text = f"✅ Imported {len(rows)} turbines."
        else:
            await io_boards_replace(rows)
            boards, pins = {}, {}
            for r in rows:
                boards.setdefault(
                    r["board"], {"name": r["board_name"], "can": r["can_node"]}
                )
                pins.setdefault(r["board"], []).append(
                    {
                        "section": r["section"],
                        "pin": r["pin"],
                        "description": r["description"],
                    }
                )
            SETTINGS.content.IO_BOARDS = boards
            current = context.bot_data.setdefault("io_boards", {})
            current.clear()
            current.update(pins)
            text = f"✅ Imported {len(boards)} IO boards with {len(rows)} pins."
        kb = [[TO_IMPORT]]

    else:
        context.user_data.pop("import_draft", None)
        text, kb = "Nothing was imported.", [[TO_IMPORT]]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = (context.user_data.get("state") or "").split(":")[-1]
    message = update.message
    if kind not in KINDS or not is_owner(update.effective_user.id):
        return
    try:
        await message.delete()
    except Exception:
        pass

    label, required, optional, thing = KINDS[kind]
    document = message.document
    errors, rows, text = [], [], ""
    if not document or not (document.file_name or "").lower().endswith(".csv"):
        errors.append("Send the list as a .csv file.")
    elif (document.file_size or 0) > MAX_IMPORT_BYTES:
        errors.append("That file is over 1 MB.")
    else:
        data = await (await document.get_file()).download_as_bytearray()
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append('Save the file as "CSV UTF-8" and send it again.')

    if not errors:
        reader = csv.DictReader(io.StringIO(text))
        columns = [(c or "").strip() for c in reader.fieldnames or []]
        missing = [c for c in required if c not in columns]
        if missing:
            errors.append(f"Missing columns: {', '.join(missing)}.")
        else:
            prefix = SETTINGS.wtg_prefix.upper()
            seen = {}
            for line, raw in enumerate(reader, 2):
                r = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                if not any(r.values()):
                    continue
                if kind == "wtgs":
                    name = r["name"].upper()
                    if not re.fullmatch(rf"{re.escape(prefix)}[A-Z]\d{{2}}", name):
                        errors.append(
                            f"Row {line}: {name or 'no name'} isn't a turbine name "
                            f"Search WTG Serials can find, like {prefix}A05."
                        )
                    elif name in seen:
                        errors.append(
                            f"Row {line}: {name} is also on row {seen[name]}."
                        )
                    elif len(r["serial"]) > 64 or len(r["ip"]) > 64:
                        errors.append(f"Row {line}: the serial or IP is too long.")
                    seen.setdefault(name, line)
                    rows.append(
                        {
                            "wtg": name,
                            "serial": r["serial"] or None,
                            "ip": r["ip"] or None,
                        }
                    )
                else:
                    key = r["board"].lower()
                    board = (r["board_name"], r.get("can_node", ""))
                    if not re.fullmatch(r"[a-z0-9_]{1,32}", key):
                        errors.append(
                            f"Row {line}: board must be letters, numbers or _, "
                            "up to 32."
                        )
                    elif not all(r[c] for c in required):
                        errors.append(f"Row {line}: board_name and pin can't be blank.")
                    elif any(
                        len(r.get(c, "")) > 100
                        for c in ["board_name", "pin", "section", "can_node"]
                    ):
                        errors.append(f"Row {line}: a value is over 100 characters.")
                    elif seen.setdefault(key, (board, line))[0] != board:
                        errors.append(
                            f"Row {line}: {key} has a different board_name or "
                            f"can_node from row {seen[key][1]}."
                        )
                    rows.append(
                        {
                            "board": key,
                            "board_name": r["board_name"],
                            "can_node": r.get("can_node", ""),
                            "section": r.get("section") or None,
                            "pin": r["pin"],
                            "description": r.get("description") or None,
                        }
                    )
            if not rows and not errors:
                errors.append("The file has no rows.")

    kb = [[TO_IMPORT]]
    if errors:
        summary = (
            "⚠️ *Nothing was saved.* Fix these and send the file again:\n\n"
            + "\n".join(f"• {escape_markdown(e)}" for e in errors[:10])
            + (f"\n…and {len(errors) - 10} more." if len(errors) > 10 else "")
        )
    else:
        context.user_data["state"] = None
        context.user_data["import_draft"] = {"kind": kind, "rows": rows}
        if kind == "wtgs":
            old = SETTINGS.content.WTG_MAP
            new = {r["wtg"]: r for r in rows}
            changed = [
                w
                for w in new.keys() & old.keys()
                if str(old[w].get("serial") or "") != str(new[w]["serial"] or "")
                or (old[w].get("ip") or "") != (new[w]["ip"] or "")
            ]
            counts = (
                len(new.keys() - old.keys()),
                len(changed),
                len(old.keys() - new.keys()),
            )
            summary = f"📥 *{len(rows)} turbines*"
        else:
            old = context.bot_data.get("io_boards", {})
            new = {}
            for r in rows:
                new.setdefault(r["board"], []).append(
                    {k: r[k] for k in ("section", "pin", "description")}
                )
            changed = [
                k
                for k in new.keys() & old.keys()
                if new[k] != old[k]
                or SETTINGS.content.IO_BOARDS.get(k, {}).get("name")
                != next(r["board_name"] for r in rows if r["board"] == k)
            ]
            counts = (
                len(new.keys() - old.keys()),
                len(changed),
                len(old.keys() - new.keys()),
            )
            summary = f"📥 *{len(new)} IO boards, {len(rows)} pins*"
        summary += f"\n\n{counts[0]} new, {counts[1]} changed, {counts[2]} removed." + (
            "\n\n⚠️ Removed ones are deleted." if counts[2] else ""
        )
        kb = [
            [
                InlineKeyboardButton(
                    "✅ Import", callback_data="troubleshooter:import:save"
                ),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data="troubleshooter:import:cancel"
                ),
            ]
        ]

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=context.user_data.get("last_msg_id"),
        text=summary,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
