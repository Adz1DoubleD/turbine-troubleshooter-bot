import json
from types import SimpleNamespace

import sentry_sdk

from ..settings import SETTINGS
from .content import CONTENT_ITEMS, content_from_json
from .core import db_session


async def init_troubleshooter_db(application):
    codes = {}
    io_boards = {}
    admins = {}
    parts = []
    requests = {"access": {}, "admin": {}}
    suggestions = {}

    try:
        async with db_session() as cur:
            await cur.execute("SHOW TABLES LIKE 'content'")
            if not await cur.fetchone():
                print("🔄 Creating Troubleshooter Content table...")
                await cur.execute("""
                    CREATE TABLE content (
                        name VARCHAR(64) PRIMARY KEY,
                        data MEDIUMTEXT NOT NULL
                    ) DEFAULT CHARSET=utf8mb4
                """)
            await cur.execute("SELECT name, data FROM content")
            stored = {
                r["name"]: content_from_json(r["data"]) for r in await cur.fetchall()
            }
            if CONTENT_ITEMS <= stored.keys():
                SETTINGS.content = SimpleNamespace(**stored)
                print(
                    f"✅ Troubleshooter content loaded from database ({len(stored)} items)."
                )
            elif SETTINGS.content is None:
                print("❌ Troubleshooter content missing from database - menus empty.")
                sentry_sdk.capture_message(
                    "Troubleshooter content missing from database", level="error"
                )
                SETTINGS.content = SimpleNamespace(
                    MODULES_MAP={}, WTG_MAP={}, IO_BOARDS={}, PART_ACCESSORIES=()
                )

            await cur.execute("SHOW TABLES LIKE 'codes'")
            if not await cur.fetchone():
                print("🔄 Creating Troubleshooter Codes table...")
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
                print("🔄 Creating Troubleshooter Users table...")
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
                print("🔄 Creating Troubleshooter Parts table...")
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
                    print(
                        f"🔄 Creating Troubleshooter IO board table '{table_name}'..."
                    )
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
                print("🔄 Creating Troubleshooter Settings table...")
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
                print("🔄 Creating Troubleshooter Requests table...")
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

            await cur.execute("SHOW TABLES LIKE 'suggestions'")
            if not await cur.fetchone():
                print("🔄 Creating Troubleshooter Suggestions table...")
                await cur.execute("""
                    CREATE TABLE suggestions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        name VARCHAR(255) DEFAULT NULL,
                        location TEXT NOT NULL,
                        title VARCHAR(100) NOT NULL,
                        body TEXT,
                        file_id VARCHAR(255) DEFAULT NULL,
                        file_kind VARCHAR(10) DEFAULT NULL,
                        created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            await cur.execute(
                "SELECT id, user_id, name, location, title, body, file_id, file_kind "
                "FROM suggestions ORDER BY id"
            )
            for r in await cur.fetchall():
                suggestions[int(r["id"])] = {**r, "location": json.loads(r["location"])}

        application.bot_data["codes"] = codes
        application.bot_data["io_boards"] = io_boards
        application.bot_data["troubleshooter_admins"] = admins
        application.bot_data["troubleshooter_approved"] = approved
        application.bot_data["parts"] = parts
        application.bot_data["pending_access_requests"] = requests["access"]
        application.bot_data["pending_admin_requests"] = requests["admin"]
        application.bot_data["pending_suggestions"] = suggestions

        print(
            f"✅ Troubleshooter tables verified: {len(codes)} codes, "
            f"{len(io_boards)} boards, {len(parts)} parts, {len(admins)} admins "
            f"and {len(approved)} approved users loaded into RAM."
        )

    except Exception as e:
        print(f"❌ [DB] Troubleshooter DB init failed: {e}")
        sentry_sdk.capture_exception(e)
