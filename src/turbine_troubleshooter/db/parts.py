"""Saving spare parts."""

import json
from typing import Any

from .core import db_session


async def part_add(
    part_no: str,
    description: str,
    added_by: str | None = None,
    stock_no: str | None = None,
    location: str | None = None,
) -> int | None:
    async with db_session() as cur:
        await cur.execute(
            "INSERT IGNORE INTO parts "
            "(part_no, stock_no, location, description, added_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (part_no, stock_no or None, location or None, description, added_by),
        )
        return cur.lastrowid if cur.rowcount else None


async def part_update(
    part_id: int | str,
    field: str,
    value: Any,
    edited_by: str | None = None,
    edited_at: str | None = None,
    old: Any = None,
) -> bool:
    if field not in ("part_no", "stock_no", "location", "description"):
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
                        JSON_OBJECT(
                            'by', %s, 'at', %s, 'changes', CAST(%s AS JSON)
                        )
                    )
                WHERE id = %s
                """,
                (
                    value,
                    edited_by,
                    edited_at,
                    json.dumps({field: [old, value]}, ensure_ascii=False),
                    part_id,
                ),
            )
        else:
            await cur.execute(
                f"UPDATE parts SET `{field}` = %s WHERE id = %s", (value, part_id)
            )
    return True
