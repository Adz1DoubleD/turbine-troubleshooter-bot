import json
from pathlib import Path
from types import SimpleNamespace

import sentry_sdk

from ..settings import SETTINGS
from .core import db_session


async def init_troubleshooter_db(application):
    codes = {}
    io_boards = {}
    admins = {}
    parts = []
    requests = {"access": {}, "admin": {}}
    delete_requests = {}

    SETTINGS.content = SimpleNamespace(WTG_MAP={}, IO_BOARDS={})

    try:
        async with db_session() as cur:
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

            await cur.execute("SHOW TABLES LIKE 'menus'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE menus (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        parent_id INT NULL,
                        type VARCHAR(10) NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        body TEXT NULL,
                        sort_order INT NOT NULL DEFAULT 0,
                        verified TINYINT NOT NULL DEFAULT 0,
                        created_by BIGINT NULL,
                        updated_by BIGINT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        edits JSON NULL,
                        KEY parent_order (parent_id, sort_order),
                        FOREIGN KEY (parent_id) REFERENCES menus (id)
                    ) DEFAULT CHARSET=utf8mb4
                """)

            await cur.execute("SHOW TABLES LIKE 'attachments'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE attachments (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        node_id INT NULL,
                        type VARCHAR(10) NOT NULL,
                        file_id VARCHAR(255) NULL,
                        file_unique_id VARCHAR(64) NULL,
                        path VARCHAR(255) NULL,
                        status VARCHAR(10) NOT NULL DEFAULT 'pending',
                        caption VARCHAR(1024) NULL,
                        sort_order INT NOT NULL DEFAULT 0,
                        created_by BIGINT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        KEY node_order (node_id, sort_order),
                        KEY file_unique (file_unique_id),
                        FOREIGN KEY (node_id) REFERENCES menus (id)
                            ON DELETE CASCADE
                    ) DEFAULT CHARSET=utf8mb4
                """)

            await cur.execute("SHOW TABLES LIKE 'io_boards'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE io_boards (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        board VARCHAR(32) NOT NULL,
                        board_name VARCHAR(100) NOT NULL,
                        can_node VARCHAR(100) NULL,
                        section VARCHAR(100) NULL,
                        pin VARCHAR(100) NULL,
                        description TEXT NULL,
                        position INT NOT NULL DEFAULT 0,
                        KEY board_position (board, position)
                    ) DEFAULT CHARSET=utf8mb4
                """)

            await cur.execute("SHOW TABLES LIKE 'wtgs'")
            if not await cur.fetchone():
                await cur.execute("""
                    CREATE TABLE wtgs (
                        wtg VARCHAR(32) PRIMARY KEY,
                        serial VARCHAR(64) NULL,
                        ip VARCHAR(64) NULL,
                        sort_order INT NOT NULL DEFAULT 0
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

        try:
            async with db_session() as cur:
                await cur.execute(
                    "SELECT id, parent_id, type, title, body, sort_order, "
                    "created_by, edits FROM menus ORDER BY sort_order, id"
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
                    if a["status"] in ("pending", "committed")
                    and a["path"]
                    and SETTINGS.files_dir
                    and (Path(SETTINGS.files_dir) / a["path"]).is_file()
                ]
                lost = [
                    a
                    for a in attachments
                    if a["status"] == "saved"
                    and a["file_id"]
                    and a["path"]
                    and SETTINGS.files_dir
                    and not (Path(SETTINGS.files_dir) / a["path"]).is_file()
                ]
                if lost:
                    await cur.execute(
                        "UPDATE attachments SET status = 'pending' WHERE id IN ("
                        + ", ".join(["%s"] * len(lost))
                        + ")",
                        [a["id"] for a in lost],
                    )
                    for a in lost:
                        a["status"] = "pending"
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
            print(f"❌ [DB] Troubleshooter menus failed to load: {e}")
            sentry_sdk.capture_exception(e)

        try:
            async with db_session() as cur:
                await cur.execute(
                    "SELECT board, board_name, can_node, section, pin, description "
                    "FROM io_boards ORDER BY board, position, id"
                )
                boards, pins = {}, {}
                for r in await cur.fetchall():
                    boards.setdefault(
                        r["board"],
                        {"name": r["board_name"], "can": r["can_node"] or ""},
                    )
                    pins.setdefault(r["board"], []).append(
                        {
                            "section": r["section"],
                            "pin": r["pin"],
                            "description": r["description"],
                        }
                    )
                SETTINGS.content.IO_BOARDS = boards
                io_boards.clear()
                io_boards.update(pins)
        except Exception as e:
            print(f"❌ [DB] Troubleshooter IO boards failed to load: {e}")
            sentry_sdk.capture_exception(e)

        try:
            async with db_session() as cur:
                await cur.execute(
                    "SELECT wtg, serial, ip FROM wtgs ORDER BY sort_order, wtg"
                )
                SETTINGS.content.WTG_MAP = {
                    r["wtg"]: {"serial": r["serial"], "ip": r["ip"]}
                    for r in await cur.fetchall()
                }
        except Exception as e:
            print(f"❌ [DB] Troubleshooter turbines failed to load: {e}")
            sentry_sdk.capture_exception(e)

        print(
            f"✅ Troubleshooter database ready: {len(codes)} codes, "
            f"{len(parts)} parts, "
            f"{len((SETTINGS.menu or {}).get('nodes', []))} menu items, "
            f"{len(io_boards)} IO boards, {len(SETTINGS.content.WTG_MAP)} turbines, "
            f"{len(admins)} admins, {len(approved)} approved users"
        )

    except Exception as e:
        print(f"❌ [DB] Troubleshooter DB init failed: {e}")
        sentry_sdk.capture_exception(e)
