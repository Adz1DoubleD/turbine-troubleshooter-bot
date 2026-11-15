import asyncio
import csv
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import aiomysql
import sentry_sdk

from troubleshooter.settings import SETTINGS

EXPORT_TABLES = ("codes", "parts", "users", "io_boards")
CONTENT_ITEMS = {"MODULES_MAP", "WTG_MAP", "IO_BOARDS", "PART_ACCESSORIES"}
FILE_PREFIX = "file:"


DB_POOL_SIZE = 3
DB_CONNECT_TIMEOUT = 10
DB_POOL_RECYCLE = 280

_pool = None
_pool_lock = asyncio.Lock()


async def get_db_pool():
    global _pool
    async with _pool_lock:
        if _pool is None:
            db_url = urlparse(
                os.environ.get("TROUBLESHOOTER_DB_URL")
                or os.environ.get("JAWSDB_URL")
                or ""
            )
            _pool = await aiomysql.create_pool(
                host=db_url.hostname,
                user=db_url.username,
                password=db_url.password,
                port=db_url.port,
                db=db_url.path[1:],
                autocommit=True,
                minsize=1,
                maxsize=DB_POOL_SIZE,
                connect_timeout=DB_CONNECT_TIMEOUT,
                pool_recycle=DB_POOL_RECYCLE,
            )
    return _pool


@asynccontextmanager
async def db_session():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                yield cur
            except Exception as e:
                sentry_sdk.capture_exception(e)
                raise


async def close_db():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def get_neighbours(curr_id: int, table: str, order_by: str = "id"):
    async with db_session() as cur:
        await cur.execute(
            f"""
            SELECT
                (SELECT id FROM `{table}` WHERE `{order_by}` < c.`{order_by}`
                 ORDER BY `{order_by}` DESC LIMIT 1) AS prev_id,
                (SELECT id FROM `{table}` WHERE `{order_by}` > c.`{order_by}`
                 ORDER BY `{order_by}` ASC LIMIT 1) AS next_id
            FROM `{table}` c
            WHERE c.id = %s
        """,
            (curr_id,),
        )
        row = await cur.fetchone()
        return (row["prev_id"], row["next_id"]) if row else (None, None)


def content_from_json(text):
    def resolve(obj):
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(v) for v in obj]
        if isinstance(obj, str) and obj.startswith(FILE_PREFIX):
            path = Path(SETTINGS.files_dir) / obj[len(FILE_PREFIX) :]
            if not path.is_file():
                print(f"⚠️ Troubleshooter file missing: {obj[len(FILE_PREFIX) :]}")
                sentry_sdk.capture_message(
                    f"Troubleshooter file missing: {obj[len(FILE_PREFIX) :]}",
                    level="warning",
                )
            return path
        return obj

    return resolve(json.loads(text))


async def init_troubleshooter_db(application):
    codes = {}
    io_boards = {}
    admins = {}
    parts = []

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

        application.bot_data["codes"] = codes
        application.bot_data["io_boards"] = io_boards
        application.bot_data["troubleshooter_admins"] = admins
        application.bot_data["troubleshooter_approved"] = approved
        application.bot_data["parts"] = parts

        print(
            f"✅ Troubleshooter tables verified: {len(codes)} codes, "
            f"{len(io_boards)} boards, {len(parts)} parts, {len(admins)} admins "
            f"and {len(approved)} approved users loaded into RAM."
        )

    except Exception as e:
        print(f"❌ [DB] Troubleshooter DB init failed: {e}")
        sentry_sdk.capture_exception(e)


def db_export(rows):
    rows = list(rows)

    headers = []
    for r in rows:
        for k in r:
            if k not in headers:
                headers.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        line = {}
        for k in headers:
            v = r.get(k)
            if isinstance(v, datetime):
                v = v.strftime("%Y-%m-%d %H:%M")
            elif isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            elif v is None:
                v = ""
            line[k] = v
        writer.writerow(line)

    bio = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    buf.close()
    return bio


async def db_tables(table):
    if table not in EXPORT_TABLES:
        return None
    async with db_session() as cur:
        await cur.execute("SHOW TABLES")
        names = {next(iter(r.values())) for r in await cur.fetchall()}

        if table == "io_boards":
            merged = []
            for board in SETTINGS.content.IO_BOARDS:
                if board not in names:
                    continue
                await cur.execute(f"SELECT * FROM `{board}`")
                for r in await cur.fetchall():
                    merged.append({"board": board, **r})
            return merged

        if table not in names:
            return None

        await cur.execute(f"SELECT * FROM `{table}`")
        return await cur.fetchall()


async def fault_code_add(**kwargs):
    params = {
        "code": kwargs["code"],
        "advice": kwargs.get("advice"),
        "parts": kwargs.get("parts"),
        "added_by": kwargs.get("added_by"),
        "added_at": kwargs.get("added_at"),
        "edited_by": kwargs.get("edited_by") or kwargs.get("added_by"),
        "edited_at": kwargs.get("edited_at"),
    }
    query = """
    INSERT INTO codes (code, advice, parts, added_by, added_at)
    VALUES (
        %(code)s, %(advice)s, %(parts)s, %(added_by)s, COALESCE(%(added_at)s, NOW())
    ) AS new
    ON DUPLICATE KEY UPDATE
        advice = new.advice,
        parts = new.parts,
        edits = JSON_ARRAY_APPEND(
            COALESCE(codes.edits, JSON_ARRAY()),
            '$',
            JSON_OBJECT(
                'by', %(edited_by)s,
                'at', COALESCE(%(edited_at)s, DATE_FORMAT(NOW(), '%%Y-%%m-%%d %%H:%%i'))
            )
        )
    """
    async with db_session() as cur:
        await cur.execute(query, params)
        await cur.execute("SELECT id FROM codes WHERE code = %s", (params["code"],))
        row = await cur.fetchone()
        return row["id"] if row else None


async def admin_add(user_id, username=None):
    query = """
    INSERT INTO users (user_id, username, is_admin)
    VALUES (%(user_id)s, %(username)s, 1) AS new
    ON DUPLICATE KEY UPDATE
        username = new.username,
        is_admin = 1
    """
    async with db_session() as cur:
        await cur.execute(query, {"user_id": user_id, "username": username})


async def admin_remove(user_id):
    query = "UPDATE users SET is_admin = 0 WHERE user_id = %s"
    async with db_session() as cur:
        await cur.execute(query, (user_id,))
        return cur.rowcount > 0


async def user_add(user_id, username=None):
    async with db_session() as cur:
        await cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        exists = await cur.fetchone()

        if not exists:
            await cur.execute(
                "INSERT INTO users (user_id, username, is_admin, last_login) "
                "VALUES (%s, %s, 0, NOW())",
                (user_id, username),
            )
            return True

        await cur.execute(
            "UPDATE users SET username = %s, last_login = NOW() WHERE user_id = %s",
            (username, user_id),
        )
        return False


async def user_approve(user_id):
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET is_approved = 1 WHERE user_id = %s", (user_id,)
        )
        return cur.rowcount > 0


async def user_revoke(user_id):
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET is_approved = 0 WHERE user_id = %s", (user_id,)
        )
        return cur.rowcount > 0


async def users_get():
    async with db_session() as cur:
        await cur.execute(
            "SELECT user_id, username, is_admin, last_login, notifications_enabled, "
            "is_approved FROM users"
        )
        records = await cur.fetchall()

        return [
            {
                "user_id": int(record["user_id"]),
                "username": record.get("username"),
                "is_admin": int(record["is_admin"]),
                "last_login": record.get("last_login"),
                "notifications_enabled": int(record.get("notifications_enabled", 1)),
                "is_approved": int(record.get("is_approved") or 0),
            }
            for record in records
        ]


async def user_notifications_toggle(user_id):
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET notifications_enabled = 1 - notifications_enabled WHERE user_id = %s",
            (user_id,),
        )
        await cur.execute(
            "SELECT notifications_enabled FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()
        return int(row["notifications_enabled"]) if row else None


async def setting_toggle(name):
    async with db_session() as cur:
        await cur.execute(
            "INSERT INTO settings (name, value) VALUES (%s, 0) "
            "ON DUPLICATE KEY UPDATE value = 1 - value",
            (name,),
        )
        await cur.execute("SELECT value FROM settings WHERE name = %s", (name,))
        row = await cur.fetchone()
    SETTINGS.notify_settings[name] = int(row["value"]) if row else 1
    return SETTINGS.notify_settings[name]


async def user_notifications_get(user_id):
    async with db_session() as cur:
        await cur.execute(
            "SELECT notifications_enabled FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()
        return int(row["notifications_enabled"]) if row else 1


async def part_add(part_no, description, section="", added_by=None):
    async with db_session() as cur:
        await cur.execute(
            "INSERT IGNORE INTO parts (part_no, description, section, added_by) "
            "VALUES (%s, %s, %s, %s)",
            (part_no, description, section, added_by),
        )
        return cur.lastrowid if cur.rowcount else None


async def part_update(part_id, field, value, edited_by=None, edited_at=None):
    if field not in ("part_no", "description", "section"):
        raise ValueError(f"Unknown part field: {field}")
    async with db_session() as cur:
        if edited_by:
            await cur.execute(
                f"""
                UPDATE parts SET
                    `{field}` = %s,
                    edits = JSON_ARRAY_APPEND(
                        COALESCE(edits, JSON_ARRAY()),
                        '$',
                        JSON_OBJECT('by', %s, 'at', %s)
                    )
                WHERE id = %s
                """,
                (value, edited_by, edited_at, part_id),
            )
        else:
            await cur.execute(
                f"UPDATE parts SET `{field}` = %s WHERE id = %s", (value, part_id)
            )
    return True


async def delete_entry(table, column, value):
    async with db_session() as cur:
        await cur.execute(f"DELETE FROM `{table}` WHERE `{column}` = %s", (value,))
        return cur.rowcount > 0
