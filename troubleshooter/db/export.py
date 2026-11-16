import csv
import io
import json
from datetime import datetime

from ..settings import SETTINGS
from .core import db_session

EXPORT_TABLES = ("codes", "parts", "users", "io_boards")


def db_export(rows):
    rows = list(rows)

    headers = []
    for r in rows:
        for k in r:
            if k not in headers:
                headers.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
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
        await cur.execute("SHOW TABLES")
        names = {next(iter(r.values())) for r in await cur.fetchall()}

        if table == "io_boards":
            merged = []
            for board in SETTINGS.content.IO_BOARDS:
                if board not in names:
                    continue
                await cur.execute(f"SELECT * FROM `{board}`")
                for r in await cur.fetchall():
                    merged.append({"board": board, **r})
            return merged

        if table not in names:
            return None

        await cur.execute(f"SELECT * FROM `{table}`")
        return await cur.fetchall()
