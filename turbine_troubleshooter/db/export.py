import csv
import io
import json
from datetime import datetime

from ..settings import SETTINGS
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

        if table in ("menus", "wtgs"):
            content_name = {
                "menus": "MODULES_MAP",
                "wtgs": "WTG_MAP",
            }[table]

            await cur.execute(
                "SELECT `data` FROM `content` WHERE `name` = %s LIMIT 1",
                (content_name,),
            )

            rows = await cur.fetchall()

            if not rows:
                return None

            data = rows[0]["data"]

            if isinstance(data, bytes):
                data = data.decode("utf-8")

            if isinstance(data, str):
                data = json.loads(data)

            if not isinstance(data, dict):
                return None

            result = []

            for name, details in data.items():
                row = {"name": name}

                if isinstance(details, dict):
                    row.update(details)
                    row["name"] = name
                else:
                    row["value"] = details

                result.append(row)

            return result

        await cur.execute("SHOW TABLES")
        names = {next(iter(r.values())) for r in await cur.fetchall()}

        if table == "io_boards" and "io_boards" not in names:
            merged = []

            for board in SETTINGS.content.IO_BOARDS:
                if board not in names:
                    continue

                await cur.execute(f"SELECT * FROM `{board}`")

                for r in await cur.fetchall():
                    merged.append(
                        {
                            "board": board,
                            **r,
                        }
                    )

            return merged

        if table not in names:
            return None

        await cur.execute(f"SELECT * FROM `{table}`")

        return await cur.fetchall()
