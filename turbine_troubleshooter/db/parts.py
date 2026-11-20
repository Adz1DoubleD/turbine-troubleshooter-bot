"""Saving spare parts."""

import json

from .core import db_session


async def part_add(part_no, description, section="", added_by=None):
    async with db_session() as cur:
        await cur.execute(
            "INSERT IGNORE INTO parts (part_no, description, section, added_by) "
            "VALUES (%s, %s, %s, %s)",
            (part_no, description, section, added_by),
        )
        return cur.lastrowid if cur.rowcount else None


async def part_update(part_id, field, value, edited_by=None, edited_at=None, old=None):
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
