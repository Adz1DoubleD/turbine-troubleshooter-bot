import json

from .core import db_session


async def menu_node_add(parent_id, kind, title, body, user_id):
    async with db_session() as cur:
        await cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM menus "
            "WHERE parent_id <=> %s",
            (parent_id,),
        )
        order = (await cur.fetchone())["n"]
        await cur.execute(
            "INSERT INTO menus (parent_id, type, title, body, sort_order, "
            "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (parent_id, kind, title, body, order, user_id, user_id),
        )
        return {
            "id": cur.lastrowid,
            "parent_id": parent_id,
            "type": kind,
            "title": title,
            "body": body,
            "sort_order": order,
            "created_by": user_id,
            "edits": [],
        }


async def menu_node_update(node_id, field, value, user_id, edited_by, edited_at, old):
    if field not in ("title", "body"):
        raise ValueError(f"Unknown menu field: {field}")
    async with db_session() as cur:
        await cur.execute(
            f"""
            UPDATE menus SET
                `{field}` = %s,
                updated_by = %s,
                edits = JSON_ARRAY_APPEND(
                    COALESCE(edits, JSON_ARRAY()),
                    '$',
                    JSON_OBJECT('by', %s, 'at', %s, 'changes', CAST(%s AS JSON))
                )
            WHERE id = %s
            """,
            (
                value,
                user_id,
                edited_by,
                edited_at,
                json.dumps({field: [old, value]}, ensure_ascii=False),
                node_id,
            ),
        )
        return cur.rowcount > 0


async def menu_node_delete(node_id):
    async with db_session() as cur:
        await cur.execute("DELETE FROM menus WHERE id = %s", (node_id,))
        return cur.rowcount > 0


async def attachment_add(node_id, kind, file_id, file_unique_id, path, user_id):
    async with db_session() as cur:
        await cur.execute(
            "INSERT INTO attachments (node_id, type, file_id, file_unique_id, path, "
            "status, sort_order, created_by) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', 1, %s)",
            (node_id, kind, file_id, file_unique_id, path, user_id),
        )
        return {
            "id": cur.lastrowid,
            "node_id": node_id,
            "type": kind,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "path": path,
            "status": "pending",
        }


async def attachments_remove(node_id):
    async with db_session() as cur:
        await cur.execute("DELETE FROM attachments WHERE node_id = %s", (node_id,))
        return cur.rowcount


async def attachment_status(attachment_id, status):
    async with db_session() as cur:
        await cur.execute(
            "UPDATE attachments SET status = %s WHERE id = %s", (status, attachment_id)
        )
        return cur.rowcount > 0
