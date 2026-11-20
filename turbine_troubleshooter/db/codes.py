"""Saving fault codes."""

import json
from typing import Any

from .core import db_session


async def fault_code_add(**kwargs: Any) -> int | None:
    params = {
        "code": kwargs["code"],
        "advice": kwargs.get("advice"),
        "parts": kwargs.get("parts"),
        "added_by": kwargs.get("added_by"),
        "added_at": kwargs.get("added_at"),
        "edited_by": kwargs.get("edited_by") or kwargs.get("added_by"),
        "edited_at": kwargs.get("edited_at"),
        "changes": json.dumps(kwargs["changes"], ensure_ascii=False)
        if kwargs.get("changes")
        else None,
    }
    query = """
    INSERT INTO codes (code, advice, parts, added_by, added_at)
    VALUES (
        %(code)s, %(advice)s, %(parts)s, %(added_by)s, COALESCE(%(added_at)s, NOW())
    ) AS new
    ON DUPLICATE KEY UPDATE
        advice = new.advice,
        parts = new.parts,
        edits = JSON_ARRAY_APPEND(
            COALESCE(codes.edits, JSON_ARRAY()),
            '$',
            JSON_OBJECT(
                'by', %(edited_by)s,
                'at', COALESCE(%(edited_at)s, DATE_FORMAT(NOW(), '%%Y-%%m-%%d %%H:%%i')),
                'changes', CAST(%(changes)s AS JSON)
            )
        )
    """
    async with db_session() as cur:
        await cur.execute(query, params)
        await cur.execute("SELECT id FROM codes WHERE code = %s", (params["code"],))
        row = await cur.fetchone()
        return row["id"] if row else None
