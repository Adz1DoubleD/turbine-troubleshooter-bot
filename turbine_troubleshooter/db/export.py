"""Exporting tables as CSV."""

import csv
import io
import json
from datetime import datetime

from .core import db_session

EXPORT_TABLES = (
    "codes",
    "parts",
    "users",
    "io_boards",
    "menus",
    "wtgs",
)


def db_export(rows):
    rows = list(rows)

    headers = []
    for r in rows:
        for k in r:
            if k not in headers:
                headers.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=headers,
        extrasaction="ignore",
    )
    writer.writeheader()

    for r in rows:
        line = {}

        for k in headers:
            v = r.get(k)

            if isinstance(v, datetime):
                v = v.strftime("%Y-%m-%d %H:%M")
            elif isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            elif v is None:
                v = ""

            line[k] = v

        writer.writerow(line)

    bio = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    buf.close()

    return bio


async def db_tables(table):
    if table not in EXPORT_TABLES:
        return None

    async with db_session() as cur:
        await cur.execute("SHOW TABLES LIKE 'wtgs'")
        if table == "wtgs" and await cur.fetchone():
            await cur.execute(
                "SELECT wtg AS name, serial, ip FROM wtgs ORDER BY sort_order, wtg"
            )
            return await cur.fetchall() or None

        if table == "menus":
            await cur.execute("SHOW TABLES LIKE 'menus'")
            if await cur.fetchone():
                await cur.execute(
                    "SELECT id, parent_id, type, title, body, sort_order "
                    "FROM menus ORDER BY sort_order, id"
                )
                children = {}
                for n in await cur.fetchall():
                    children.setdefault(n["parent_id"], []).append(n)
                await cur.execute(
                    "SELECT node_id, path FROM attachments ORDER BY sort_order, id"
                )
                files = {}
                for a in await cur.fetchall():
                    files.setdefault(a["node_id"], []).append(a["path"] or "")
                rows = []
                stack = [(n, (n["title"],)) for n in reversed(children.get(None, []))]
                while stack:
                    n, path = stack.pop()
                    rows.append(
                        {
                            "id": n["id"],
                            "path": " › ".join(path),
                            "type": n["type"],
                            "title": n["title"],
                            "body": n["body"],
                            "files": ", ".join(files.get(n["id"], [])),
                            "parent_id": n["parent_id"],
                            "position": n["sort_order"],
                        }
                    )
                    stack += [
                        (c, (*path, c["title"]))
                        for c in reversed(children.get(n["id"], []))
                    ]
                return rows or None

        await cur.execute("SHOW TABLES")
        names = {next(iter(r.values())) for r in await cur.fetchall()}

        if table not in names:
            return None

        await cur.execute(f"SELECT * FROM `{table}`")

        return await cur.fetchall()
