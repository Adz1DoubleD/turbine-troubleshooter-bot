import json
from pathlib import Path

import sentry_sdk

from ..settings import SETTINGS
from .core import db_session

CONTENT_ITEMS = {"MODULES_MAP", "WTG_MAP", "IO_BOARDS"}
FILE_PREFIX = "file:"


def content_from_json(text):
    def resolve(obj):
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(v) for v in obj]
        if isinstance(obj, str) and obj.startswith(FILE_PREFIX):
            path = Path(SETTINGS.files_dir) / obj[len(FILE_PREFIX) :]
            if not path.is_file():
                print(f"⚠️ Troubleshooter file missing: {obj[len(FILE_PREFIX) :]}")
                sentry_sdk.capture_message(
                    f"Troubleshooter file missing: {obj[len(FILE_PREFIX) :]}",
                    level="warning",
                )
            return path
        return obj

    return resolve(json.loads(text))


def content_to_json(obj):
    if isinstance(obj, Path):
        try:
            rel = obj.relative_to(Path(SETTINGS.files_dir)).as_posix()
        except (TypeError, ValueError):
            rel = obj.as_posix()
        return f"{FILE_PREFIX}{rel}"
    if isinstance(obj, dict):
        return {k: content_to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [content_to_json(v) for v in obj]
    return obj


async def content_save():
    async with db_session() as cur:
        for name in sorted(CONTENT_ITEMS):
            data = content_to_json(getattr(SETTINGS.content, name))
            await cur.execute(
                "INSERT INTO content (name, data) VALUES (%s, %s) AS new "
                "ON DUPLICATE KEY UPDATE data = new.data",
                (name, json.dumps(data, ensure_ascii=False)),
            )
