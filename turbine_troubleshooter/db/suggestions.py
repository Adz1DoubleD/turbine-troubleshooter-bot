import json

from .core import db_session


async def suggestion_add(s):
    async with db_session() as cur:
        await cur.execute(
            "INSERT INTO suggestions "
            "(user_id, name, location, title, body, file_id, file_kind) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                s["user_id"],
                s["name"],
                json.dumps(s["location"], ensure_ascii=False),
                s["title"],
                s["body"],
                s["file_id"],
                s["file_kind"],
            ),
        )
        return cur.lastrowid


async def suggestion_remove(suggestion_id):
    async with db_session() as cur:
        await cur.execute("DELETE FROM suggestions WHERE id = %s", (suggestion_id,))
