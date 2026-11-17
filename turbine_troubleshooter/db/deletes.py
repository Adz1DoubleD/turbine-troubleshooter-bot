from .core import db_session


async def delete_request_add(kind, target, label, user_id, name):
    async with db_session() as cur:
        await cur.execute(
            "INSERT IGNORE INTO delete_requests (kind, target, label, user_id, name) "
            "VALUES (%s, %s, %s, %s, %s)",
            (kind, str(target), label[:255], user_id, name),
        )
        return cur.lastrowid if cur.rowcount else None


async def delete_request_remove(request_id):
    async with db_session() as cur:
        await cur.execute("DELETE FROM delete_requests WHERE id = %s", (request_id,))
        return cur.rowcount > 0
