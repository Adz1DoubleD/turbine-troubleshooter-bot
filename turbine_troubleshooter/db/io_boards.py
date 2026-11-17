import json

from .core import db_session

IO_BOARDS_MIGRATED = "io_boards_migrated"


async def io_boards_migrate(io_boards_json):
    async with db_session() as cur:
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

        await cur.execute(
            "SELECT value FROM settings WHERE name = %s", (IO_BOARDS_MIGRATED,)
        )
        if await cur.fetchone():
            return 0

        pins = []
        for key, info in (json.loads(io_boards_json) if io_boards_json else {}).items():
            await cur.execute("SHOW TABLES LIKE %s", (key,))
            if not await cur.fetchone():
                continue
            await cur.execute(
                f"SELECT section, connector AS pin, tdi_text AS description FROM `{key}` "
                "ORDER BY id"
            )
            info = info if isinstance(info, dict) else {"name": str(info)}
            pins += [
                (
                    key,
                    info.get("name") or key.upper(),
                    info.get("can", ""),
                    r["section"],
                    r["pin"],
                    r["description"],
                    order,
                )
                for order, r in enumerate(await cur.fetchall(), 1)
            ]

        await cur.execute("START TRANSACTION")
        try:
            for pin in pins:
                await cur.execute(
                    "INSERT INTO io_boards (board, board_name, can_node, section, "
                    "pin, description, position) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    pin,
                )
            await cur.execute(
                "INSERT INTO settings (name, value) VALUES (%s, 1)",
                (IO_BOARDS_MIGRATED,),
            )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise

    return len(pins)


async def io_boards_replace(pins):
    async with db_session() as cur:
        await cur.execute("START TRANSACTION")
        try:
            await cur.execute("DELETE FROM io_boards")
            orders = {}
            for p in pins:
                orders[p["board"]] = orders.get(p["board"], 0) + 1
                await cur.execute(
                    "INSERT INTO io_boards (board, board_name, can_node, section, "
                    "pin, description, position) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        p["board"],
                        p["board_name"],
                        p["can_node"],
                        p["section"],
                        p["pin"],
                        p["description"],
                        orders[p["board"]],
                    ),
                )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise
