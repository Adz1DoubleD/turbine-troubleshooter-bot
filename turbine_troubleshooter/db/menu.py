import json

from ..settings import SETTINGS
from .content import FILE_PREFIX
from .core import db_session

MENU_MIGRATED = "menu_migrated"


async def menu_migrate(modules_map_json):
    async with db_session() as cur:
        await cur.execute("SHOW TABLES LIKE 'menu_nodes'")
        if not await cur.fetchone():
            await cur.execute("""
                CREATE TABLE menu_nodes (
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
                    KEY parent_order (parent_id, sort_order),
                    FOREIGN KEY (parent_id) REFERENCES menu_nodes (id)
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
                    FOREIGN KEY (node_id) REFERENCES menu_nodes (id)
                        ON DELETE CASCADE
                ) DEFAULT CHARSET=utf8mb4
            """)

        await cur.execute(
            "SELECT value FROM settings WHERE name = %s", (MENU_MIGRATED,)
        )
        if await cur.fetchone() or not modules_map_json:
            return 0

        owner = int(SETTINGS.owner_id) if SETTINGS.owner_id else None
        queue = [
            (None, (), title, data, order)
            for order, (title, data) in enumerate(
                json.loads(modules_map_json).items(), 1
            )
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
                    "INSERT INTO menu_nodes (parent_id, type, title, body, "
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

                for media in ("photo", "document"):
                    file = data.get(media) if isinstance(data, dict) else None
                    if isinstance(file, str) and file.startswith(FILE_PREFIX):
                        await cur.execute(
                            "INSERT INTO attachments (node_id, type, path, status, "
                            "sort_order, created_by) "
                            "VALUES (%s, %s, %s, 'saved', 1, %s)",
                            (node_id, media, file[len(FILE_PREFIX) :], owner),
                        )

            await cur.execute(
                "INSERT INTO settings (name, value) VALUES (%s, 1)", (MENU_MIGRATED,)
            )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise

    return len(queue)
