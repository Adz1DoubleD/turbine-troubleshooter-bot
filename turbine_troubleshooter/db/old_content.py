import json
import re

from .core import db_session

COPIED_MARKERS = ("menu_migrated", "io_boards_migrated", "wtgs_migrated")
KEEP_TABLES = {
    "attachments",
    "codes",
    "delete_requests",
    "io_boards",
    "menus",
    "parts",
    "requests",
    "settings",
    "users",
    "wtgs",
}


async def old_content_remove():
    async with db_session() as cur:
        await cur.execute("SHOW TABLES")
        names = {next(iter(r.values())) for r in await cur.fetchall()}
        if "content" not in names:
            return None

        await cur.execute(
            "SELECT name FROM settings WHERE name IN (%s, %s, %s)", COPIED_MARKERS
        )
        if len(await cur.fetchall()) < len(COPIED_MARKERS):
            return False

        await cur.execute("SELECT data FROM content WHERE name = 'IO_BOARDS'")
        row = await cur.fetchone()
        boards = json.loads(row["data"]) if row else {}
        removed = [
            b
            for b in boards
            if b in names and b not in KEEP_TABLES and re.fullmatch(r"\w+", b)
        ]
        if "suggestions" in names:
            removed.append("suggestions")
        for table in removed:
            await cur.execute(f"DROP TABLE IF EXISTS `{table}`")

        await cur.execute("SHOW COLUMNS FROM menus LIKE 'legacy_key'")
        if await cur.fetchone():
            await cur.execute("ALTER TABLE menus DROP COLUMN legacy_key")

        await cur.execute("DROP TABLE IF EXISTS content")
        await cur.execute(
            "DELETE FROM settings WHERE name IN (%s, %s, %s)", COPIED_MARKERS
        )
    return removed + ["content"]
