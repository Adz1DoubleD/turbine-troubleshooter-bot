"""Replacing the IO board pin-outs."""

from typing import Any

from .core import db_session


async def io_boards_replace(pins: list[dict[str, Any]]) -> None:
    async with db_session() as cur:
        await cur.execute("START TRANSACTION")
        try:
            await cur.execute("DELETE FROM io_boards")
            orders: dict[Any, Any] = {}
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
