import json

from ..settings import SETTINGS
from .content import FILE_PREFIX
from .core import db_session

MENU_MIGRATED = "menu_migrated"


async def menu_migrate(menus_json):
    async with db_session() as cur:
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
                    legacy_key VARCHAR(512) NULL UNIQUE,
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

        await cur.execute(
            "SELECT value FROM settings WHERE name = %s", (MENU_MIGRATED,)
        )
        if await cur.fetchone():
            return 0
        if not menus_json:
            await cur.execute(
                "INSERT INTO settings (name, value) VALUES (%s, 1)", (MENU_MIGRATED,)
            )
            return 0

        owner = int(SETTINGS.owner_id) if SETTINGS.owner_id else None
        queue = [
            (None, (), title, data, order)
            for order, (title, data) in enumerate(json.loads(menus_json).items(), 1)
        ]

        await cur.execute("START TRANSACTION")
        try:
            for parent_id, path, title, data, order in queue:
                if isinstance(data, dict) and "menu" in data:
                    kind, body = "submenu", None
                elif isinstance(data, dict):
                    kind, body = "page", data.get("text")
                else:
                    kind, body = "page", data

                await cur.execute(
                    "INSERT INTO menus (parent_id, type, title, body, "
                    "sort_order, created_by, updated_by, legacy_key) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        parent_id,
                        kind,
                        title,
                        body,
                        order,
                        owner,
                        owner,
                        json.dumps([*path, title], ensure_ascii=False),
                    ),
                )
                node_id = cur.lastrowid

                if kind == "submenu":
                    queue += [
                        (node_id, (*path, title), t, d, o)
                        for o, (t, d) in enumerate(data["menu"].items(), 1)
                    ]
                    continue

                files = [
                    (media, file)
                    for media in ("photo", "document")
                    if isinstance(data, dict)
                    for file in (
                        data.get(media)
                        if isinstance(data.get(media), list)
                        else [data.get(media)]
                    )
                    if isinstance(file, str) and file.startswith(FILE_PREFIX)
                ]
                for order, (media, file) in enumerate(files, 1):
                    await cur.execute(
                        "INSERT INTO attachments (node_id, type, path, status, "
                        "sort_order, created_by) "
                        "VALUES (%s, %s, %s, 'saved', %s, %s)",
                        (node_id, media, file[len(FILE_PREFIX) :], order, owner),
                    )

            await cur.execute(
                "INSERT INTO settings (name, value) VALUES (%s, 1)", (MENU_MIGRATED,)
            )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise

    return len(queue)


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
