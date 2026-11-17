import json
from pathlib import Path
from types import SimpleNamespace

import sentry_sdk

from ..settings import SETTINGS
from .content import CONTENT_ITEMS, content_from_json
from .core import db_session
from .io_boards import IO_BOARDS_MIGRATED, io_boards_migrate
from .menu import MENU_MIGRATED, menu_migrate


async def init_troubleshooter_db(application):
    codes = {}
    io_boards = {}
    admins = {}
    parts = []
    requests = {"access": {}, "admin": {}}
    delete_requests = {}

    try:
        async with db_session() as cur:
            await cur.execute("SHOW TABLES LIKE 'content'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE content (
                        name VARCHAR(64) PRIMARY KEY,
                        data MEDIUMTEXT NOT NULL
                    ) DEFAULT CHARSET=utf8mb4
                """)

            await cur.execute("SELECT name, data FROM content")
            rows = await cur.fetchall()

            stored = {r["name"]: content_from_json(r["data"]) for r in rows}

            content_names = list(stored)

            if CONTENT_ITEMS <= stored.keys():
                SETTINGS.content = SimpleNamespace(**stored)
            elif SETTINGS.content is None:
                sentry_sdk.capture_message(
                    "Troubleshooter content missing from database", level="error"
                )
                SETTINGS.content = SimpleNamespace(
                    MODULES_MAP={}, WTG_MAP={}, IO_BOARDS={}
                )

            await cur.execute("SHOW TABLES LIKE 'codes'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE codes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(50) NOT NULL UNIQUE,
                        advice TEXT,
                        parts TEXT,
                        added_by TEXT DEFAULT NULL,
                        added_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
                        edits JSON NULL
                    )
                """)

            await cur.execute("SHOW TABLES LIKE 'users'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE users (
                        user_id BIGINT PRIMARY KEY,
                        username VARCHAR(255) DEFAULT NULL,
                        is_admin TINYINT DEFAULT 0,
                        last_login DATETIME NULL,
                        notifications_enabled TINYINT DEFAULT 1,
                        is_approved TINYINT DEFAULT 0
                    )
                """)

            await cur.execute("SHOW TABLES LIKE 'parts'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE parts (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        part_no VARCHAR(20) NOT NULL,
                        description VARCHAR(160) NOT NULL,
                        section VARCHAR(60) NOT NULL,
                        added_by TEXT DEFAULT NULL,
                        edits JSON NULL,
                        UNIQUE KEY part_section (part_no, section)
                    )
                """)

            for table_name in SETTINGS.content.IO_BOARDS.keys():
                await cur.execute(f"SHOW TABLES LIKE '{table_name}'")
                if not await cur.fetchone():
                    await cur.execute(f"""
                        CREATE TABLE `{table_name}` (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            section VARCHAR(100),
                            connector VARCHAR(100),
                            tdi_text TEXT
                        )
                    """)

            await cur.execute(
                "SELECT id, code, advice, parts, added_by, added_at, edits FROM codes"
            )
            f_records = await cur.fetchall()

            for record in f_records:
                clean_code = str(record["code"]).strip()
                codes[clean_code] = {
                    "id": record["id"],
                    "code": record["code"],
                    "advice": record["advice"],
                    "parts": record["parts"],
                    "added_by": record.get("added_by"),
                    "added_at": record.get("added_at"),
                    "edits": json.loads(record["edits"]) if record.get("edits") else [],
                }

            for table_name in SETTINGS.content.IO_BOARDS.keys():
                await cur.execute(
                    f"SELECT section, connector, tdi_text FROM `{table_name}`"
                )
                io_records = await cur.fetchall()

                if io_records:
                    io_boards[table_name] = [
                        {
                            "section": r.get("section", ""),
                            "connector": r.get("connector", ""),
                            "tdi_text": r.get("tdi_text", ""),
                        }
                        for r in io_records
                    ]

            await cur.execute("SELECT user_id, username FROM users WHERE is_admin = 1")
            records = await cur.fetchall()

            for record in records:
                user_id = int(record["user_id"])
                username = record.get("username")
                admins[user_id] = username

            await cur.execute(
                "SELECT user_id FROM users WHERE is_approved = 1 OR is_admin = 1"
            )
            approved = {int(r["user_id"]) for r in await cur.fetchall()}

            await cur.execute(
                "SELECT id, part_no, description, section, added_by, edits FROM parts"
            )
            parts = [
                {
                    "id": r["id"],
                    "part_no": r["part_no"],
                    "description": r["description"],
                    "section": r["section"],
                    "added_by": r.get("added_by"),
                    "edits": json.loads(r["edits"]) if r.get("edits") else [],
                }
                for r in await cur.fetchall()
            ]

            await cur.execute("SHOW TABLES LIKE 'settings'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE settings (
                        name VARCHAR(64) PRIMARY KEY,
                        value TINYINT NOT NULL DEFAULT 1
                    )
                """)

            await cur.execute("SELECT name, value FROM settings")
            SETTINGS.notify_settings = {
                r["name"]: int(r["value"]) for r in await cur.fetchall()
            }

            await cur.execute("SHOW TABLES LIKE 'requests'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE requests (
                        user_id BIGINT PRIMARY KEY,
                        kind VARCHAR(10) NOT NULL,
                        name VARCHAR(255) DEFAULT NULL,
                        requested_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

            await cur.execute("SELECT user_id, kind, name FROM requests")
            for r in await cur.fetchall():
                if r["kind"] in requests:
                    uid = int(r["user_id"])
                    requests[r["kind"]][uid] = r["name"] or str(uid)

            await cur.execute("SHOW TABLES LIKE 'delete_requests'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE delete_requests (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        kind VARCHAR(10) NOT NULL,
                        target VARCHAR(64) NOT NULL,
                        label VARCHAR(255) NOT NULL,
                        user_id BIGINT NOT NULL,
                        name VARCHAR(255) DEFAULT NULL,
                        requested_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY kind_target (kind, target)
                    ) DEFAULT CHARSET=utf8mb4
                """)

            await cur.execute(
                "SELECT id, kind, target, label, user_id, name "
                "FROM delete_requests ORDER BY id"
            )
            for r in await cur.fetchall():
                delete_requests[int(r["id"])] = r

        application.bot_data["codes"] = codes
        application.bot_data["io_boards"] = io_boards
        application.bot_data["troubleshooter_admins"] = admins
        application.bot_data["troubleshooter_approved"] = approved
        application.bot_data["parts"] = parts
        application.bot_data["pending_access_requests"] = requests["access"]
        application.bot_data["pending_admin_requests"] = requests["admin"]
        application.bot_data["pending_delete_requests"] = delete_requests

        print(
            f"✅ Troubleshooter database initialised:\n"
            f"   Content: {', '.join(content_names) if content_names else 'None'}\n"
            f"   Codes: {len(codes)}\n"
            f"   IO Boards: {len(io_boards)}\n"
            f"   Parts: {len(parts)}\n"
            f"   Admins: {len(admins)}\n"
            f"   Approved Users: {len(approved)}"
        )

        try:
            migrated = await menu_migrate(
                next((r["data"] for r in rows if r["name"] == "MODULES_MAP"), None)
            )
            if migrated:
                print(f"✅ Troubleshooter menu copied to menu_nodes: {migrated} items")
            async with db_session() as cur:
                await cur.execute(
                    "SELECT value FROM settings WHERE name = %s", (MENU_MIGRATED,)
                )
                if await cur.fetchone():
                    await cur.execute(
                        "SELECT id, parent_id, type, title, body, sort_order, "
                        "created_by, edits FROM menu_nodes ORDER BY sort_order, id"
                    )
                    nodes = [
                        {**n, "edits": json.loads(n["edits"]) if n.get("edits") else []}
                        for n in await cur.fetchall()
                    ]
                    await cur.execute(
                        "SELECT id, node_id, type, file_id, file_unique_id, path, "
                        "status FROM attachments WHERE node_id IS NOT NULL "
                        "ORDER BY sort_order, id"
                    )
                    attachments = await cur.fetchall()
                    saved = [
                        a
                        for a in attachments
                        if a["status"] == "pending"
                        and a["path"]
                        and SETTINGS.files_dir
                        and (Path(SETTINGS.files_dir) / a["path"]).is_file()
                    ]
                    if saved:
                        await cur.execute(
                            "UPDATE attachments SET status = 'saved' WHERE id IN ("
                            + ", ".join(["%s"] * len(saved))
                            + ")",
                            [a["id"] for a in saved],
                        )
                        for a in saved:
                            a["status"] = "saved"
                    SETTINGS.menu = {"nodes": nodes, "attachments": attachments}
        except Exception as e:
            print(f"❌ [DB] Troubleshooter menu copy failed: {e}")
            sentry_sdk.capture_exception(e)

        try:
            copied = await io_boards_migrate(
                next((r["data"] for r in rows if r["name"] == "IO_BOARDS"), None)
            )
            if copied:
                print(f"✅ Troubleshooter IO boards copied to io_boards: {copied} pins")
            async with db_session() as cur:
                await cur.execute(
                    "SELECT value FROM settings WHERE name = %s", (IO_BOARDS_MIGRATED,)
                )
                if await cur.fetchone():
                    await cur.execute(
                        "SELECT board_key, board_name, can_node, section, connector, "
                        "tdi_text FROM io_boards ORDER BY board_key, sort_order, id"
                    )
                    boards, pins = {}, {}
                    for r in await cur.fetchall():
                        boards.setdefault(
                            r["board_key"],
                            {"name": r["board_name"], "can": r["can_node"] or ""},
                        )
                        pins.setdefault(r["board_key"], []).append(
                            {
                                "section": r["section"],
                                "connector": r["connector"],
                                "tdi_text": r["tdi_text"],
                            }
                        )
                    SETTINGS.content = SimpleNamespace(
                        MODULES_MAP=SETTINGS.content.MODULES_MAP,
                        WTG_MAP=SETTINGS.content.WTG_MAP,
                        IO_BOARDS=boards,
                    )
                    io_boards.clear()
                    io_boards.update(pins)
        except Exception as e:
            print(f"❌ [DB] Troubleshooter IO board copy failed: {e}")
            sentry_sdk.capture_exception(e)

    except Exception as e:
        print(f"❌ [DB] Troubleshooter DB init failed: {e}")
        sentry_sdk.capture_exception(e)
