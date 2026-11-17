import json
from pathlib import Path

import sentry_sdk

from ..settings import SETTINGS

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
